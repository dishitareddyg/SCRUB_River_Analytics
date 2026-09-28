"""
communication/mqtt_client.py

Thin wrapper around paho-mqtt for autonomous navigation bot telemetry.
Best-effort non-blocking publish; auto-reconnects in background.
"""

from __future__ import annotations

import json

try:
    import paho.mqtt.client as mqtt
except ImportError:
    class _MockMqttClient:
        def __init__(self, *args, **kwargs): pass
        def username_pw_set(self, *args, **kwargs): pass
        def reconnect_delay_set(self, *args, **kwargs): pass
        def connect_async(self, *args, **kwargs): pass
        def loop_start(self): pass
        def loop_stop(self): pass
        def disconnect(self): pass
        def publish(self, *args, **kwargs): pass
    class _MockMqttModule:
        Client = _MockMqttClient
    mqtt = _MockMqttModule()  # type: ignore

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


class MQTTClient:
    def __init__(self, health=None):
        self._health = health
        self._connected = False
        self._client = mqtt.Client(client_id=settings.MQTT_CLIENT_ID, clean_session=True)

        if settings.MQTT_USERNAME:
            self._client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(
            min_delay=1, max_delay=max(settings.MQTT_RECONNECT_DELAY, 1)
        )

    def start(self) -> None:
        try:
            self._client.connect_async(
                settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, settings.MQTT_KEEPALIVE
            )
            self._client.loop_start()
            logger.info(
                "MQTT client starting (broker=%s:%s)",
                settings.MQTT_BROKER_HOST,
                settings.MQTT_BROKER_PORT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("MQTT initial connect failed: %s", exc)

    def stop(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def publish(self, topic_suffix: str, payload: dict) -> None:
        """Best-effort telemetry publish. Never raises."""
        topic = f"{settings.MQTT_BASE_TOPIC}/{settings.DEVICE_ID}/{topic_suffix}"
        try:
            body = json.dumps(payload, default=str)
            self._client.publish(topic, body, qos=settings.MQTT_QOS, retain=settings.MQTT_RETAIN)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MQTT publish failed for topic %s: %s", topic, exc)

    def _on_connect(self, _client, _userdata, _flags, rc) -> None:
        if rc == 0:
            self._connected = True
            logger.info("MQTT connected")
            if self._health:
                self._health.set_mqtt_connected(True)
        else:
            logger.warning("MQTT connect failed with rc=%s", rc)
            if self._health:
                self._health.set_mqtt_connected(False)

    def _on_disconnect(self, _client, _userdata, rc) -> None:
        self._connected = False
        if self._health:
            self._health.set_mqtt_connected(False)
        if rc != 0:
            logger.warning("MQTT disconnected unexpectedly (rc=%s)", rc)
        else:
            logger.info("MQTT disconnected")
