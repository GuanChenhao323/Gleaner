import 'package:mqtt_client/mqtt_client.dart';
import 'package:mqtt_client/mqtt_server_client.dart';

/// 手机与桌面端：直接 TCP 连接自研 Broker（1883，生产环境 8883 + TLS）。
MqttClient createMqttClient(Uri server, String clientId) {
  const port = int.fromEnvironment('GLEANER_MQTT_PORT', defaultValue: 1883);
  final c = MqttServerClient.withPort(server.host, clientId, port);
  c.secure = server.scheme == 'https' && port == 8883;
  return c;
}
