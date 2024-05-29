# adapted from https://github.com/laksjdjf/cgem156-ComfyUI/blob/main/scripts/attention_couple/node.py
# by @laksjdjf

import torch
import torch.nn.functional as F
import math
from torch import Tensor, Size
from comfy.model_patcher import ModelPatcher

from .nodes import ListWrapper


def get_mask(mask: Tensor, batch_size: int, num_tokens: int, original_shape: Size) -> Tensor:
    num_conds = mask.shape[0]

    if original_shape[2] * original_shape[3] == num_tokens:
        down_sample_rate = 1
    elif (original_shape[2] // 2) * (original_shape[3] // 2) == num_tokens:
        down_sample_rate = 2
    elif (original_shape[2] // 4) * (original_shape[3] // 4) == num_tokens:
        down_sample_rate = 4
    else:
        down_sample_rate = 8

    size = (original_shape[2] // down_sample_rate, original_shape[3] // down_sample_rate)
    mask_downsample: Tensor = F.interpolate(mask, size=size, mode="nearest")
    mask_downsample = mask_downsample.view(num_conds, num_tokens, 1)
    mask_downsample = mask_downsample.repeat_interleave(batch_size, dim=0)
    return mask_downsample


def lcm(a: int, b: int):
    return a * b // math.gcd(a, b)


def lcm_for_list(numbers: list[int]):
    current_lcm = numbers[0]
    for number in numbers[1:]:
        current_lcm = lcm(current_lcm, number)
    return current_lcm


class AttentionCouple:

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "base_mask": ("MASK",),
                "regions": ("LIST",),
            }
        }

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "attention_couple"
    CATEGORY = "_external_tooling"

    mask: Tensor
    conds: list[Tensor]
    batch_size: int

    def attention_couple(self, model: ModelPatcher, base_mask: Tensor, regions: ListWrapper):
        new_model = model.clone()
        num_conds = len(regions.content) + 1

        mask = torch.stack([base_mask] + [r["mask"] for r in regions.content], dim=0)
        mask_sum = mask.sum(dim=0, keepdim=True)
        assert mask_sum.sum() > 0, "There are areas that are zero in all masks."
        self.mask = mask / mask_sum

        self.conds = [r["conditioning"][0][0] for r in regions.content]
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
            conds_tensor = torch.cat(
                [
                    cond.repeat(self.batch_size, lcm_tokens // num_tokens[i], 1)
                    for i, cond in enumerate(self.conds)
                ],
                dim=0,
            )

            qs, ks = [], []
            for i, cond_or_uncond in enumerate(cond_or_unconds):
                k_target = k_chunks[i].repeat(1, lcm_tokens // k.shape[1], 1)
                if cond_or_uncond == 1:  # uncond
                    qs.append(q_chunks[i])
                    ks.append(k_target)
                else:
                    qs.append(q_chunks[i].repeat(num_conds, 1, 1))
                    ks.append(torch.cat([k_target, conds_tensor], dim=0))

            qs = torch.cat(qs, dim=0)
            ks = torch.cat(ks, dim=0)

            return qs, ks, ks

        def attn2_output_patch(out: Tensor, extra_options: dict):
            cond_or_unconds = extra_options["cond_or_uncond"]
            mask_downsample = get_mask(
                self.mask, self.batch_size, out.shape[1], extra_options["original_shape"]
            )
            outputs: list[Tensor] = []
            pos = 0
            for cond_or_uncond in cond_or_unconds:
                if cond_or_uncond == 1:  # uncond
                    outputs.append(out[pos : pos + self.batch_size])
                    pos += self.batch_size
                else:
                    masked_output = (
                        out[pos : pos + num_conds * self.batch_size] * mask_downsample
                    ).view(num_conds, self.batch_size, out.shape[1], out.shape[2])
                    masked_output = masked_output.sum(dim=0)
                    outputs.append(masked_output)
                    pos += num_conds * self.batch_size
            return torch.cat(outputs, dim=0)

        new_model.set_model_attn2_patch(attn2_patch)
        new_model.set_model_attn2_output_patch(attn2_output_patch)
        return (new_model,)
