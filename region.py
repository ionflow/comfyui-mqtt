# Adapted from https://github.com/laksjdjf/cgem156-ComfyUI/blob/main/scripts/attention_couple/node.py
# by @laksjdjf

from typing import NamedTuple
import torch
import torch.nn.functional as F
import math
from torch import Tensor, Size
from comfy.model_patcher import ModelPatcher

from .nodes import ListWrapper


def downsample_mask(mask: Tensor, batch: int, target_size: int, original_shape: Size) -> Tensor:
    h, w = original_shape[2], original_shape[3]
    hm, wm = mask.shape[2], mask.shape[3]
    if (h, w) == (hm, wm):  # Mask is already in latent resolution
        base_factor = 1
    elif (h * 8, w * 8) == (hm, wm):  # Mask is in image resolution, downsample by 8
        base_factor = 8
    else:
        raise ValueError(f"Bad mask size. Expected {w}x{h}, got {wm}x{hm}.")

    result = mask
    for factor in [1, 2, 4, 8]:
        size = (math.ceil(h / factor), math.ceil(w / factor))
        if size[0] * size[1] == target_size and base_factor * factor > 1:
            result = F.interpolate(mask, size=size, mode="nearest")
            break

    num_conds = mask.shape[0]
    result = result.view(num_conds, target_size, 1)
    result = result.repeat_interleave(batch, dim=0)
    return result


def lcm(a: int, b: int):
    return a * b // math.gcd(a, b)


def lcm_for_list(numbers: list[int]):
    current_lcm = numbers[0]
    for number in numbers[1:]:
        current_lcm = lcm(current_lcm, number)
    return current_lcm


class Region(NamedTuple):
    previous: "Region" | None
    mask: Tensor
    conditioning: dict

    def to_list(self):
        result: list[Region] = []
        current = self
        while current is not None:
            result.append(current)
            current = current.previous
        return result


class DefineRegion:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mask": ("MASK",),
                "conditioning": ("CONDITIONING",),
            },
            "optional": {
                "regions": ("REGIONS",),
            },
        }

    CATEGORY = "external_tooling/regions"
    RETURN_TYPES = ("REGIONS",)
    FUNCTION = "define"

    def define(self, mask: Tensor, conditioning: dict, regions: Region | None = None):
        return (Region(regions, mask, conditioning),)


class AttentionMask:

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "regions": ("REGIONS",),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "attention_mask"
    CATEGORY = "external_tooling/regions"

    mask: Tensor
    conds: list[Tensor]
    batch_size: int

    def attention_mask(self, model: ModelPatcher, regions: Region):
        new_model = model.clone()
        region_list = regions.to_list()
        num_conds = len(region_list)

        mask = torch.stack([r["mask"] for r in region_list], dim=0)
        mask_sum = mask.sum(dim=0, keepdim=True)
        assert mask_sum.sum() > 0, "There are areas that are zero in all masks."
        self.mask = mask / mask_sum

        self.conds = [r["conditioning"][0][0] for r in region_list]
        num_tokens = [cond.shape[1] for cond in self.conds]

        def attn2_patch(q: Tensor, k: Tensor, v: Tensor, extra_options: dict):
            assert k.mean() == v.mean(), "k and v must be the same."
            device, dtype = q.device, q.dtype

            if self.conds[0].device != device:
                self.conds = [cond.to(device, dtype=dtype) for cond in self.conds]
            if self.mask.device != device:
                self.mask = self.mask.to(device, dtype=dtype)

            cond_or_unconds = extra_options["cond_or_uncond"]
            num_chunks = len(cond_or_unconds)
            self.batch_size = q.shape[0] // num_chunks
            q_chunks = q.chunk(num_chunks, dim=0)
            k_chunks = k.chunk(num_chunks, dim=0)
            lcm_tokens = lcm_for_list(num_tokens + [k.shape[1]])
            conds_tensor = [
                cond.repeat(self.batch_size, lcm_tokens // num_tokens[i], 1)
                for i, cond in enumerate(self.conds)
            ]
            conds_tensor = torch.cat(conds_tensor, dim=0)

            qs, ks = [], []
            for i, cond_or_uncond in enumerate(cond_or_unconds):
                k_target = k_chunks[i].repeat(1, lcm_tokens // k.shape[1], 1)
                if cond_or_uncond == 1:  # uncond
                    qs.append(q_chunks[i])
                    ks.append(k_target)
                else:
                    qs.append(q_chunks[i].repeat(num_conds, 1, 1))
                    ks.append(conds_tensor)

            qs = torch.cat(qs, dim=0)
            ks = torch.cat(ks, dim=0)
            return qs, ks, ks

        def attn2_output_patch(out: Tensor, extra_options: dict):
            cond_or_unconds = extra_options["cond_or_uncond"]
            mask_downsample = downsample_mask(
                self.mask, self.batch_size, out.shape[1], extra_options["original_shape"]
            )
            outputs: list[Tensor] = []
            pos = 0
            for cond_or_uncond in cond_or_unconds:
                if cond_or_uncond == 1:  # uncond
                    outputs.append(out[pos : pos + self.batch_size])
                    pos += self.batch_size
                else:
                    masked = out[pos : pos + num_conds * self.batch_size] * mask_downsample
                    masked = masked.view(num_conds, self.batch_size, out.shape[1], out.shape[2])
                    masked = masked.sum(dim=0)
                    outputs.append(masked)
                    pos += num_conds * self.batch_size
            return torch.cat(outputs, dim=0)

        new_model.set_model_attn2_patch(attn2_patch)
        new_model.set_model_attn2_output_patch(attn2_output_patch)
        return (new_model,)
