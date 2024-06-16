from . import nodes

NODE_CLASS_MAPPINGS = {
    "CINIA_SendImageWebSocket": nodes.SendImageWebSocket,
    "CINIA_SendImageMQTT": nodes.SendImageMQTT,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "CINIA_SendImageWebSocket": "Send Image (WebSocket)",
    "CINIA_SendImageMQTT": "Send Image (MQTT)",
}
