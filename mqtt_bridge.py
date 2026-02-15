import asyncio
import json
import os
import logging
from typing import Any

import websockets
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# Setup logging for systemd visibility
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("mesh-bridge")

load_dotenv()

# Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "meshcore/terminal/rx")
WS_URL = os.getenv("WS_URL", "ws://127.0.0.1:8000/api/ws")

def on_connect(client: mqtt.Client, userdata: Any, flags: dict, rc: int):
    if rc == 0:
        logger.info(f"Connected to MQTT Broker at {MQTT_BROKER}")
    else:
        logger.error(f"Failed to connect to MQTT, return code {rc}")

# Initialize MQTT Client
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect

async def bridge():
    """Main loop to bridge WebSocket data to MQTT."""
    while True:
        try:
            # Ensure MQTT is connected
            if not mqtt_client.is_connected():
                mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
                mqtt_client.loop_start()

            async with websockets.connect(WS_URL) as websocket:
                logger.info(f"Established WebSocket connection to {WS_URL}")
                
                async for message in websocket:
                    try:
                        # Validate JSON before forwarding
                        data = json.loads(message)
                        mqtt_client.publish(MQTT_TOPIC, json.dumps(data))
                        logger.debug(f"Forwarded message type: {data.get('type')}")
                    except json.JSONDecodeError:
                        logger.warning("Received non-JSON message, skipping.")
                        
        except (websockets.ConnectionClosed, ConnectionRefusedError) as e:
            logger.error(f"Connection error: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.critical(f"Unexpected error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(bridge())
    except KeyboardInterrupt:
        logger.info("Bridge stopped by user.")
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
