import asyncio
import websockets
import json
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv

load_dotenv()

# Config from .env
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "meshcore/terminal/rx")
WS_URL = os.getenv("WS_URL", "ws://127.0.0.1:8000/api/ws")

def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT Broker with result code {rc}")

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.connect(MQTT_BROKER, 1883, 60)
mqtt_client.loop_start()

async def bridge():
    while True:
        try:
            async with websockets.connect(WS_URL) as websocket:
                print(f"Connected to MeshCore WebSocket at {WS_URL}")
                while True:
                    message = await websocket.recv()
                    # Forward the raw JSON to MQTT
                    mqtt_client.publish(MQTT_TOPIC, message)
                    print(f"Forwarded: {message[:50]}...")
        except Exception as e:
            print(f"Connection lost, retrying in 5s... Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(bridge())
