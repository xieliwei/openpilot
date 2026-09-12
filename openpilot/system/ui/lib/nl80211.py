#!/usr/bin/env python3
"""Create the softAP netdev the Hotspot runs on, so it can coexist with the station.

AGNOS ships p2p0 as an nl80211 P2P_DEVICE, which NetworkManager declines when it
enumerates links and never re-evaluates, so a second NM-managed wifi device has to be
created at runtime. phy0 allows "#{ managed } <= 2, #{ AP } <= 2".

Separate process because NEW_INTERFACE needs CAP_NET_ADMIN; stdlib only so sudo does not
need the venv or PYTHONPATH.
"""
import errno
import os
import socket
import struct
import sys

NETLINK_GENERIC = 16
GENL_ID_CTRL = 0x10
CTRL_CMD_GETFAMILY = 3
CTRL_ATTR_FAMILY_ID = 1
CTRL_ATTR_FAMILY_NAME = 2

NLM_F_REQUEST = 0x01
NLM_F_ACK = 0x04
NLMSG_ERROR = 2
NLMSG_DONE = 3

NL80211_CMD_SET_INTERFACE = 6
NL80211_CMD_NEW_INTERFACE = 7
NL80211_CMD_DEL_INTERFACE = 8

NL80211_ATTR_WIPHY = 1
NL80211_ATTR_IFINDEX = 3
NL80211_ATTR_IFNAME = 4
NL80211_ATTR_IFTYPE = 5

NL80211_IFTYPE_AP = 3


def _nla(attr_type: int, payload: bytes) -> bytes:
  length = 4 + len(payload)
  return struct.pack("=HH", length, attr_type) + payload + b"\x00" * ((-length) % 4)


def _nla_u32(attr_type: int, value: int) -> bytes:
  return _nla(attr_type, struct.pack("=I", value))


def _nla_str(attr_type: int, value: str) -> bytes:
  return _nla(attr_type, value.encode() + b"\x00")


class Nl80211:
  def __init__(self):
    self._sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_GENERIC)
    self._sock.settimeout(5.0)
    self._sock.bind((0, 0))
    self._pid = self._sock.getsockname()[0]
    self._seq = 0
    self._family = self._resolve_family("nl80211")

  def _send(self, family: int, cmd: int, flags: int, attrs: bytes, version: int = 0) -> None:
    self._seq += 1
    payload = struct.pack("=BBH", cmd, version, 0) + attrs
    header = struct.pack("=IHHII", 16 + len(payload), family, flags, self._seq, self._pid)
    self._sock.send(header + payload)

  def _recv(self) -> list[bytes]:
    bodies: list[bytes] = []
    while True:
      data = self._sock.recv(65536)
      offset = 0
      while offset + 16 <= len(data):
        msg_len, msg_type = struct.unpack_from("=IH", data, offset)
        if msg_len < 16:
          return bodies
        body = data[offset + 16:offset + msg_len]
        if msg_type == NLMSG_ERROR:
          err = struct.unpack_from("=i", body, 0)[0]
          if err != 0:
            raise OSError(-err, os.strerror(-err))
          return bodies
        if msg_type == NLMSG_DONE:
          return bodies
        bodies.append(body)
        offset += (msg_len + 3) & ~3
      if bodies:
        return bodies

  def _resolve_family(self, name: str) -> int:
    self._send(GENL_ID_CTRL, CTRL_CMD_GETFAMILY, NLM_F_REQUEST, _nla_str(CTRL_ATTR_FAMILY_NAME, name), version=1)
    for body in self._recv():
      offset = 4
      while offset + 4 <= len(body):
        length, attr_type = struct.unpack_from("=HH", body, offset)
        if length < 4:
          break
        if (attr_type & 0x3FFF) == CTRL_ATTR_FAMILY_ID:
          return struct.unpack_from("=H", body, offset + 4)[0]
        offset += (length + 3) & ~3
    raise RuntimeError(f"netlink family {name} not found")

  def _do(self, cmd: int, attrs: bytes) -> None:
    self._send(self._family, cmd, NLM_F_REQUEST | NLM_F_ACK, attrs)
    self._recv()

  def add_ap_iface(self, ifname: str) -> None:
    try:
      self._do(NL80211_CMD_NEW_INTERFACE, _nla_u32(NL80211_ATTR_WIPHY, 0) + _nla_str(NL80211_ATTR_IFNAME, ifname) +
               _nla_u32(NL80211_ATTR_IFTYPE, NL80211_IFTYPE_AP))
    except OSError as e:
      if e.errno != errno.EEXIST:
        raise

    # NEW_INTERFACE has been seen returning a station netdev, so set the iftype explicitly
    self._do(NL80211_CMD_SET_INTERFACE, _nla_u32(NL80211_ATTR_IFINDEX, socket.if_nametoindex(ifname)) +
             _nla_u32(NL80211_ATTR_IFTYPE, NL80211_IFTYPE_AP))

  def del_iface(self, ifname: str) -> None:
    try:
      index = socket.if_nametoindex(ifname)
    except OSError:
      return
    self._do(NL80211_CMD_DEL_INTERFACE, _nla_u32(NL80211_ATTR_IFINDEX, index))


def main() -> int:
  if len(sys.argv) != 3 or sys.argv[1] not in ("add", "del"):
    print(f"usage: {sys.argv[0]} add|del <ifname>", file=sys.stderr)
    return 2

  action, ifname = sys.argv[1], sys.argv[2]
  try:
    if action == "add":
      Nl80211().add_ap_iface(ifname)
    else:
      Nl80211().del_iface(ifname)
  except OSError as e:
    print(f"{action} {ifname} failed: {e}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
