# Firmware ESP8266

Projet PlatformIO — carte `esp12e`, framework `arduino`.

- Capteurs : DHT22, MQ-2, PIR
- Sorties : OLED I2C (0x3C), buzzer, LED bicolore
- Envoi des mesures en MQTTS vers Mosquitto (topic `sentinel/capteurs`)
- Réception des commandes (topic `sentinel/commandes`)
