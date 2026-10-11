# ddburn 🔥

A tiny, safe frontend for `dd`. Pick an ISO, pick a USB stick, burn it. That's it.

Born from wanting [Rufus](https://rufus.ie)-style simplicity on Linux without the footguns of raw `dd`.

## Run it

```bash
sudo python3 ddburn.py
```

(Or just `python3 ddburn.py` — it'll escalate to root itself via pkexec/sudo.)

**Needs:** Python 3 + tkinter (`sudo apt install python3-tk` on Debian/Ubuntu/MX).

## Safety features

- Only lists **whole disks** — never partitions, so you can't nuke `sdb1` thinking it's the stick
- Removable USB devices shown first; internal disks hidden unless you explicitly tick the box
- Big red warning naming the exact device before every burn
- Double confirmation dialog
- Progress bar + byte counter while burning

## Why not just use dd?

You can! This is for the times you want a GUI with guardrails — picking the wrong `of=` device with raw `dd` is a rite of passage nobody wants.

## License

MIT — see [LICENSE](LICENSE).
