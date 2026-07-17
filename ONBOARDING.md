# Bandwidth — onboarding

Two parts: **A. Operator setup** (you, per new client) and **B. Client first-run** (what they do). Reusable for every client. Keep it as tidy and Apple-simple as the product — see `DESIGN.md`.

---

## A. Operator setup (per client `<name>`)
Follow `deploy/README.md` to stand up the instance (user `bw-<name>`, sandboxed service, subdomain, TLS, basic-auth). Then connect **their** Claude so actions run on *their* subscription:

```sh
ssh -i ~/.ssh/lewkai_deploy root@<box-ip>
sudo -iu bw-<name>        # become the sandboxed service user
claude                    # complete the login with the CLIENT's Claude account (URL + code)
exit
sudo systemctl restart bandwidth-<name>
```

Hand the client their URL + basic-auth login. The board starts empty → they see the Welcome steps.

**Why the service user (not root):** the framework is read-only and the service is sandboxed (`ProtectSystem=strict`, only their data writable). Their Claude can act on their data but **cannot touch our code, the box, or other clients** — kernel-enforced.

---

## B. Client first-run (shown in-app on the empty board)
1. **Connect your Claude** — done at sign-up (step A). If an action ever says "not logged in", we reconnect it.
2. **Add what's on your plate** — click **＋ Add**. Name each project/task/concern and pick an area (Personal · Work · Business · Health…). Add them all.
3. **Organise** — drag each block to its stage; **★** the ones that matter now; set **Criticality** on the ones that would hurt if they slipped.
4. **Run your day** — each morning open **Today**: priorities, bottlenecks, and who you're waiting on — each with a one-click action (draft an email, resolve, log time, chat).

That's it. The board keeps its own honest status; you just work.

---

## Structure it creates (light, expandable)
Each item becomes a small "room" in the client's data repo — borrowed from the Nate-Jones project-room idea, kept KISS:
```
<area>/<initiative>/
  status.md     # the board reads/writes this (stage, priority, criticality, activity)
  context.md    # what it is · why it matters · key facts/links · notes (the AI's context)
```
Grow an initiative into the fuller project-room (sources / working / output) only when it earns it.
