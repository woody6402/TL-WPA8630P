# TL-WPA8630P

Status: Very early Draft, currently only as template for individual forks

Home Assistant Device Integration for TP-LINK powerline device WPA8630
- Works with:
  -  WPA8630P v2/v2.1 Hardware and latest build (2.0.6 Build 20240207 Rel.64435, 2.1.1 Build 20220605 Rel.83041)
  -  Python code adapted and derived from TL-WPA4220 (so maybe this device type is als working)
    - see: https://github.com/3v1n0/TL-WPA4220-python    
-  since blocking call were used in python library calls _hass.async_add_executor_job was used to capsulate them
-  since devices only allow one time login the login/retrieve/logout sequence is done for each sensor data retrieve

# Changes

- add device info: v0.91
- minor bugs: v0.91
- Sensors for PLC TX/RX, PLC Peers, #Wlan Clients, Wlan Channel, .... : v0.93
(under test, start with 0.91 where alle the information is available under the attribute of the main sensor)
- adding attributes to the sensors: v0.931
<img src="TL-WPA8630P-sensors.png" alt="Dashboard-Screenshot" width="400">

