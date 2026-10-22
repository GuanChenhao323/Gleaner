import 'package:mqtt_client/mqtt_browser_client.dart';
import 'package:mqtt_client/mqtt_client.dart';

/// 浏览器不能直接开 TCP：经网关 /mqtt 走 MQTT over WebSocket（子协议 mqtt）。
MqttClient createMqttClient(Uri server, String clientId) {
  final ws = server.replace(scheme: server.scheme == 'https' ? 'wss' : 'ws', path: '/mqtt');
  final c = MqttBrowserClient('${ws.scheme}://${ws.host}${ws.path}', clientId);
  c.port = ws.hasPort ? ws.port : (ws.scheme == 'wss' ? 443 : 80);
  c.websocketProtocols = MqttClientConstants.protocolsSingleDefault;
  return c;
}
