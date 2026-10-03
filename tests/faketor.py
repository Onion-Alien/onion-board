"""A stand-in for tor.exe in tests: reads the torrc it's given, writes its control port
and cookie where the torrc says, and answers the few control commands soundboard.tor
sends. How it behaves comes from FAKETOR_MODE:

  ok     bootstraps 0 -> 100% over a few polls
  stall  stays at 45% with a bootstrap warning
  die    prints an [err] line and exits straight away
  hang   never opens its control port

Each SIGNAL it gets is appended to <DataDirectory>/signals. It exits when its owning
control connection closes (TAKEOWNERSHIP), on SIGNAL SHUTDOWN, or when killed.

    python faketor.py -f torrc --defaults-torrc torrc-defaults
"""
import os
import re
import secrets
import socket
import sys
import threading
import time


def torrc_value(text: str, key: str) -> str:
    m = re.search(rf"^{key} (.*)$", text, re.M)
    if not m:
        return ""
    v = m.group(1).strip()
    if v.startswith('"'):
        v = re.sub(r"\\(.)", r"\1", v[1:-1])
    return v


def main():
    torrc = open(sys.argv[sys.argv.index("-f") + 1], encoding="utf-8").read()
    mode = os.environ.get("FAKETOR_MODE", "ok")
    data = torrc_value(torrc, "DataDirectory")
    os.makedirs(data, exist_ok=True)
    print("Oct 03 00:00:00.000 [notice] Tor 0.0.0 (fake) starting", flush=True)
    if mode == "die":
        print("Oct 03 00:00:00.000 [err] Reading config failed--see warnings above.",
              flush=True)
        sys.exit(1)
    if mode == "hang":
        time.sleep(120)
        return
    cookie = secrets.token_bytes(32)
    with open(torrc_value(torrc, "CookieAuthFile"), "wb") as f:
        f.write(cookie)
    socks = socket.socket()
    socks.bind(("127.0.0.1", 0))
    socks.listen(4)
    ctrl = socket.socket()
    ctrl.bind(("127.0.0.1", 0))
    ctrl.listen(4)
    with open(torrc_value(torrc, "ControlPortWriteToFile"), "w") as f:
        f.write(f"PORT=127.0.0.1:{ctrl.getsockname()[1]}\n")
    polls = [0]

    def serve(c):
        buf, authed, owner = b"", False, False

        def send(*lines):
            c.sendall("".join(f"{ln}\r\n" for ln in lines).encode())
        try:
            while True:
                while b"\r\n" not in buf:
                    chunk = c.recv(4096)
                    if not chunk:
                        raise EOFError
                    buf += chunk
                line, _, buf = buf.partition(b"\r\n")
                cmd, _, arg = line.decode().partition(" ")
                cmd = cmd.upper()
                if cmd == "AUTHENTICATE":
                    authed = arg.strip().lower() == cookie.hex()
                    send("250 OK" if authed else "515 Authentication failed: Wrong length")
                    continue
                if not authed:
                    send("514 Authentication required.")
                    continue
                if cmd == "TAKEOWNERSHIP":
                    owner = True
                    send("250 OK")
                elif cmd == "GETINFO":
                    out = []
                    for key in arg.split():
                        if key == "net/listeners/socks":
                            out.append(f'250-{key}="127.0.0.1:{socks.getsockname()[1]}"')
                        elif key == "status/bootstrap-phase":
                            polls[0] += 1
                            if mode == "stall":
                                out.append(f'250-{key}=WARN BOOTSTRAP PROGRESS=45 TAG=loading'
                                           '_descriptors SUMMARY="Loading relay descriptors" '
                                           'WARNING="Connection refused" REASON=CONNECTREFUSED')
                            else:
                                pct = min(100, (polls[0] - 1) * 50)
                                out.append(f'250-{key}=NOTICE BOOTSTRAP PROGRESS={pct} '
                                           f'TAG=x SUMMARY="Step {pct}"')
                        elif key == "config-text":   # a data block, for the parser
                            out += [f"250+{key}=", "SocksPort auto", ".dotted", "."]
                        else:
                            send(f'552 Unrecognized key "{key}"')
                            out = None
                            break
                    if out is not None:
                        # an event nobody asked for, mid-reply: must be skipped
                        send("650 STATUS_CLIENT NOTICE CIRCUIT_ESTABLISHED", *out, "250 OK")
                elif cmd == "SIGNAL":
                    with open(os.path.join(data, "signals"), "a") as f:
                        f.write(arg.strip() + "\n")
                    send("250 OK")
                    if arg.strip() in ("SHUTDOWN", "HALT"):
                        os._exit(0)
                else:
                    send(f'510 Unrecognized command "{cmd}"')
        except (EOFError, OSError):
            pass
        finally:
            c.close()
            if owner:
                os._exit(0)

    def accept():
        while True:
            c, _ = ctrl.accept()
            threading.Thread(target=serve, args=(c,), daemon=True).start()
    threading.Thread(target=accept, daemon=True).start()
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
