# ComfyUI Nodes for External Tooling

Provides nodes and API geared towards using ComfyUI as a backend for external tools.

## Nodes for sending images

ComfyUI exchanges images via the filesystem. This requires a
multi-step process (upload images, prompt, download images), is rather
inefficient, and invites a whole class of potential issues. It's also unclear
at which point those images will get cleaned up if ComfyUI is used
via external tools.

### Send Image (WebSocket)

Sends an output image over the client WebSocket connection as PNG binary data.

- Inputs: the image (RGB or RGBA)

This will first send one binary message for each image in the batch via WebSocket:

```
12<PNG-data>
```

That is two 32-bit integers (big endian) with values 1 and 2 followed by the PNG binary data. There is also a JSON message afterwards:

```
{'type': 'executed', 'data': {'node': '<node ID>', 'output': {'images': [{'source': 'websocket', 'content-type': 'image/png', 'type': 'output'}, ...]}, 'prompt_id': '<prompt ID>}}
```

## Installation

Download the repository and unpack into the `custom_nodes` folder in the ComfyUI installation directory.

Or clone via GIT, starting from ComfyUI installation directory:

```
cd custom_nodes
git clone https://github.com/Acly/comfyui-tooling-nodes.git
```

Restart ComfyUI and the nodes are functional.
