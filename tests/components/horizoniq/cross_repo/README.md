# Opt-in Solar broker verification

`test_cross_repo_broker.py` is deliberately skipped unless
`HORIZONIQ_CROSS_REPO_MQTT=1`. It connects a test-only paho client to the broker
named by `TEST_MQTT_BROKER`, patches only the HorizonIQ runtime MQTT seam, and
runs Solar's read-only `node-red/tests/cross-repo/sandbox-peer.js` subprocess.

Set `HORIZONIQ_SOLAR_REPO` to the Solar checkout. `TEST_MQTT_USERNAME` and
`TEST_MQTT_PASSWORD`, when needed, are passed to clients and the peer only by
environment; the test does not log them. When enabled, a missing Solar peer,
contract, Node executable, broker setting, or broker connection is a failure,
not a skip. The test cleans only retained messages it created under generated
sandbox topics and always terminates the peer and disconnects the client.
