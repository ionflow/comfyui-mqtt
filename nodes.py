from __future__ import annotations
from PIL import Image
import numpy as np
from server import PromptServer, BinaryEventTypes

import base64
from awsiot import mqtt_connection_builder  # AWS SDK import
from awscrt import io, mqtt  # AWS SDK import
import json  # For message formatting


class SendImageWebSocket:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"images": ("IMAGE",)}}

    RETURN_TYPES = ()
    FUNCTION = "send_images"
    OUTPUT_NODE = True
    CATEGORY = "external_tooling"

    def send_images(self, images):
        results = []
        for tensor in images:
            array = 255.0 * tensor.cpu().numpy()
            image = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))

            server = PromptServer.instance
            server.send_sync(
                BinaryEventTypes.UNENCODED_PREVIEW_IMAGE,
                ["PNG", image, None],
                "6511a2fc-b61b-4547-9214-81b6bb2600f7",
            )
            results.append(
                # Could put some kind of ID here, but for now just match them by index
                {"source": "websocket", "content-type": "image/png", "type": "output"}
            )

        return {"ui": {"images": results}}


class SendImageMQTT:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"images": ("IMAGE",), "topic": ("STRING", {"default": "comfyui"})}}

    RETURN_TYPES = ()
    FUNCTION = "send_images"
    OUTPUT_NODE = True
    CATEGORY = "external_tooling"

    def send_images(self, images, topic):
        # MQTT Connection (similar to AWS demo)
        mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint="a17fy107t7ygoi-ats.iot.us-east-1.amazonaws.com",  # Replace with your actual endpoint
            cert_filepath="./custom_nodes/comfyui-mqtt/wc-laptop.cert.pem",  # Replace with your local paths
            pri_key_filepath="./custom_nodes/comfyui-mqtt/wc-laptop.private.key",
            ca_filepath="./custom_nodes/comfyui-mqtt/root-CA.crt",
            client_id="comfyui_mqtt_publisher",
            clean_session=False,
            keep_alive_secs=60,
        )
        connect_future = mqtt_connection.connect()
        connect_future.result()  # Wait for connection

        for image in images:
            # Image conversion from SendImageWebSocket
            array = 255.0 * image.cpu().numpy()
            img = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))

            # Image encoding to Base64
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

            # Prepare message (simplified for now)
            message = {"image": img_str, "content_type": "image/png"}

            # Publish message to AWS IoT Core
            mqtt_connection.publish(
                topic=topic, payload=json.dumps(message), qos=mqtt.QoS.AT_LEAST_ONCE
            )

        disconnect_future = mqtt_connection.disconnect()
        disconnect_future.result()

        # We don't need to return a specific image result for this node
        return {"ui": {"images": []}}
