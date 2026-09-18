Melody-1 is a lightweight OLKB keyboard.

On the base layer, the key immediately to the right of Backspace sends F10 when
tapped. Holding it for 130 ms sends F19 and keeps it pressed until the key is
released. This uses ZMK's tap-preferred hold-tap behavior (`&mt F19 F10`).

Extended NKRO reporting is enabled so F13-F24, including F19, can be sent to the
host. Standard ZMK NKRO reporting excludes these keys. This setting is intended
for macOS and is not compatible with Android.

After updating from firmware without extended reporting, refresh the host's HID
descriptor: reconnect USB, or forget and re-pair the keyboard over Bluetooth
(clearing the matching bond on the keyboard as well). See
[ZMK's HID troubleshooting guide](https://zmk.dev/docs/troubleshooting/connection-issues).
