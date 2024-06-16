from . import nodes

NODE_CLASS_MAPPINGS = {
    "ETN_SendImageWebSocket": nodes.SendImageWebSocket,
    "ETN_SendImageMQTT": nodes.SendImageMQTT,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ETN_SendImageWebSocket": "Send Image (WebSocket)",
    "ETN_SendImageMQTT": "Send Image (MQTT)",
}
