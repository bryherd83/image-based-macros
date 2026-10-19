"""Trials: a straight line of rooms, no minimap (port of the AHK RunTrial).

Clear the room (ENEMIES reaches x/x), press Spawn (puts you in the next room's
doorway), walk in with W, repeat. Leaves after the wave set in the window.

Kept quick:
- after Spawn it carries on as soon as the picture shows you've been moved (it used to wait
  a fixed 2.5 s);
- before Spawn it gives the DPS meter (top-left) a moment to drop to 0 (2 s at most), so any
  damage after Spawn is the new room's;
- the walk-in is one steady W hold (the old spaced-out taps spent most of their time
  paused). Once the DPS meter shows damage it walks a little further (the first hit is only
  the nearest enemy) and lets go. How far in and how far past the first hit are learned
  from the last rooms (saved as trial_walk_in_sec / trial_walk_extra_sec).

Enemies can stand deeper in the room than the walk-in reaches. While the DPS meter reads 0
and enemies are left, the macro walks on along a zigzag (further in, then lanes on the
sides), each stretch in one go, and lets go as soon as damage shows up again.
"""
from __future__ import annotations

import math

import hud

KEY_NAMES = {"w": "forward", "s": "back", "a": "left", "d": "right"}
WALK_IN_RANGE = (0.6, 3.0)        # the learned walk-in stays within this (seconds of W)
EXTRA_MAX = 0.45                  # ...and never goes more than this past the first hit (more
                                  # overshoots small auras / slow meters in the trial simulator)
PROBE_SEC = 0.6                   # walk-in while the meter may still show the last room's damage


def _q3(xs):
    """3rd quartile (the value 3/4 of the way up)."""
    s = sorted(xs)
    return s[round(0.75 * (len(s) - 1))]


def step_plan(S, walked=None, sides=False):
    """Moves to try while enemies are left but nothing is being hit. Trials are a straight line
    of rooms, so: further in, straight ahead (walking sideways and back by default just
    wandered around the room). `sides` = last resort when straight in plus a Spawn retry hit
    nothing: then also a lane on the left walking back and a lane on the right walking in.
    Runs of steps are walked in one go, stopping on a hit (one step per pause if the DPS meter
    can't be read). `walked` = seconds of W already walked in from the doorway: it goes as far
    as trial_far_sec of walking from the doorway."""
    step, side = int(S.get("trial_step_ms", 300)), int(S.get("trial_side_ms", 750))
    n = int(S.get("trial_max_steps", 8))
    n1 = n
    if walked is not None:
        left = float(S.get("trial_far_sec", 3.5)) - walked
        n1 = max(1, min(n + 4, math.ceil(left * 1000 / step - 1e-6)))
    plan = [("w", step)] * n1
    if sides:
        plan += [("a", side)] + [("s", step)] * n + [("d", 2 * side)] + [("w", step)] * n + [("a", side)]
    return plan


def wait_unhidden(env, most=2.0):
    """Waits (2 s at most) while the black-squares teleport animation covers the Spawn button."""
    hidden = getattr(hud, "spawn_hidden", None)
    if hidden is None:
        return
    t0 = env.now()
    while env.now() - t0 < most:
        f = env.frame()
        if f is None or not hidden(f, getattr(env, "spawn_xy", None) or hud.SPAWN_XY):
            return
        env.status("trial: waiting for the teleport animation to finish")
        env.sleep(0.1)


def press_spawn(env):
    """Presses Spawn and waits until you've been moved: the middle of the picture changes and
    then holds still (trial_spawn_wait_sec at most). Returns the seconds it waited, or None if
    there was no Spawn button."""
    most = float(env.settings.get("trial_spawn_wait_sec", 2.5))
    wait_moved = getattr(env, "wait_moved", None)
    before = env.frame() if wait_moved else None
    wait_unhidden(env)
    for attempt in range(3):              # the button can be missed for a frame (screen fading)
        if attempt:
            wait_unhidden(env)
        if env.press_spawn(wait=0 if wait_moved else 1.0):
            break
        if attempt < 2:
            env.sleep(0.25)
    else:
        # the picture didn't match. The button never moves, so click where it was last seen and
        # count it only if the view really changed (you were moved)
        why = getattr(env, "spawn_why", None)
        env.spawn_note = why() if why else ""
        spot = getattr(env, "spawn_spot", None)
        if not (spot and wait_moved and spot()):
            return None
        env.status("trial: clicked where Spawn was last seen")
        t0 = env.now()
        if wait_moved(before, most) is None:
            return None
        env.spawn_spot_ok = getattr(env, "spawn_spot_ok", 0) + 1
        return env.now() - t0
    env.status("trial: pressed Spawn")
    t0 = env.now()
    if wait_moved:
        wait_moved(before, most)
    else:
        env.sleep(max(0.0, most - 1.0))
    return env.now() - t0


def walk_in(env, most, extra=0.0, old_txt="", clean=False, key="w"):
    """Holds W (or `key`) for up to `most` seconds. Once the DPS meter starts showing damage
    it keeps going `extra` seconds more (that first hit is only the nearest enemy) and lets go.
    `clean` = the meter read 0 just before, so any damage now is new. If it wasn't, damage
    only counts once the meter has read 0 here; while it shows damage that may be left over
    from the last room (or enemies right at the door) it goes PROBE_SEC at most.
    Returns (seconds walked, the new room's enemies seen, seconds in when the first hit showed
    up or None, meter read 0)."""
    saw, zero, dmg = False, clean, False
    hit_at = None
    run = 0
    env.set_keys({key})
    t0 = env.now()
    try:
        while env.now() - t0 < most and env.running():
            el = env.now() - t0
            if hit_at is not None and el >= hit_at + extra:
                break
            if dmg and not zero and el >= PROBE_SEC:
                break
            f = env.frame()
            if f is not None:
                e2 = hud.read_counter(f, "enemies")
                if e2:
                    env.info["enemies"] = e2.text
                    if e2.a < e2.b or (old_txt and e2.text != old_txt):
                        saw = True
                h = hud.dps_hitting(f)
                if h is False:
                    zero, run = True, 0
                elif h and not zero:
                    dmg = True
                elif h and hit_at is None:
                    run += 1
                    if run >= 2:            # two reads in a row, not a one-frame misread
                        hit_at = env.now() - t0
            env.sleep(0.03)
    finally:
        env.set_keys(set())
    return env.now() - t0, saw, hit_at, zero


class Room:
    """Bookkeeping for the room being fought in (made right after the walk-in)."""

    def __init__(self, env, S, spawned_at=None, spawn_s=None, walked=None, hit_at=None, zero=False, saw=False):
        self.start = env.now()
        self.spawned_at = spawned_at      # when Spawn was pressed (None = no Spawn)
        self.spawn_s = spawn_s            # seconds until Spawn had moved you
        self.walk_s = walked              # seconds of W in the walk-in
        self.walked = walked              # net seconds of W into the room so far (None = unknown)
        self.hit_at = hit_at              # seconds into the walk-in when the first hit showed up
        self.zero = zero                  # the DPS meter has read 0 in this room
        self.first_hit = hit_at           # how far in the first damage showed up
        self.plan = step_plan(S, walked)
        self.lane1 = next((i for i, (k, _) in enumerate(self.plan) if k != "w"), len(self.plan))
        self.steps = 0
        self.last_step = 0.0
        self.saw_fight = saw
        self.learn = walked is not None
        self.retries = 0                  # Spawn retries in this room

    def line(self, wave, secs):
        parts = [f"trial wave {wave}: {secs:.1f}s"]
        if self.spawn_s is not None:
            parts.append(f"Spawn {self.spawn_s:.1f}s")
        if self.walk_s is not None:
            parts.append(f"walk-in {self.walk_s:.1f}s" + (f" (hit at {self.hit_at:.1f}s)" if self.hit_at is not None else ""))
        parts.append(f"{self.steps} extra step(s)")
        return " · ".join(parts)


def sprint_off_for_trial(env, S):
    """Trials walk without sprint (it overshoots the enemies). Sprint is a toggle the game keeps
    on, and only switches while moving, so: if the last dungeon saw it on, walk a step and press
    it once. Unknown (no dungeon since the farm started): leave it, never guess."""
    if S.get("trial_sprint", False):
        return
    on = getattr(env, "sprint_on", None)
    toggle = getattr(env, "toggle_sprint", None)
    if on is None:
        env.log("trial: no dungeon yet to tell if sprint is on · leaving it as it is")
        return
    if not on or not toggle:
        return
    env.set_keys({"w"})
    env.sleep(0.15)
    toggle("trials walk without sprint")
    env.sleep(0.1)
    env.set_keys(set())


def run_trial(env, mode, leave_after):
    """Returns 'done', 'dungeon' (a dungeon took over), 'stopped' (F6) or 'paused' (Roblox
    wasn't the active window)."""
    S = env.settings                # (sprint stays on: the walk-in times are learned with it)
    walk_sec = float(S.get("trial_room_walk_sec", 3.0))
    walk_in_sec = min(max(float(S.get("trial_walk_in_sec", 2.0)), WALK_IN_RANGE[0]), WALK_IN_RANGE[1])
    extra_sec = min(max(float(S.get("trial_walk_extra_sec", 0.3)), 0.0), EXTRA_MAX)
    start_walk_in = (walk_in_sec, extra_sec)
    env.status(f"trial: started · leaving after wave {leave_after}")
    env.log(f"trial started · leave after wave {leave_after} · walk-in {walk_in_sec:.1f}s, {extra_sec:.1f}s past the first hit")
    env.shot("trial-started", force=True)

    no_spawn_n = spot_n = 0

    def spawn_and_walk(old_txt="", clean=False):
        nonlocal no_spawn_n, spot_n
        t = env.now()
        spot_ok = getattr(env, "spawn_spot_ok", 0)
        sp = press_spawn(env)
        if sp is not None and getattr(env, "spawn_spot_ok", 0) > spot_ok:
            spot_n += 1
        if spot_n == 1 and sp is not None and getattr(env, "spawn_spot_ok", 0) > spot_ok:
            env.log(f"trial: the Spawn picture didn't match ({getattr(env, 'spawn_note', '')})"
                    " · clicked where it was last seen and that worked · screenshot saved")
            env.shot("trial-spawn-mismatch", force=True)
        if sp is None:
            no_spawn_n += 1
            if no_spawn_n == 1:        # once per trial, with a picture of what covered it
                env.log(f"trial: can't see the Spawn button ({getattr(env, 'spawn_note', '')})"
                        " · walking instead · screenshot saved")
                env.shot("trial-no-spawn", force=True)
            return None
        walked, saw, hit_at, zero = walk_in(env, walk_in_sec, extra_sec, old_txt, clean)
        return Room(env, S, t, sp, walked, hit_at, zero, saw)

    misses = 0
    clear_since = 0.0
    last_pop = last_map = 0.0
    last_spawn = 0.0
    last_seen = None               # (enemies killed, enemies, wave) last read clearly
    last_hit = 0.0
    finals, extras = [], []       # last rooms: how far in everything died / how far past the first hit
    ended = None
    cycle_t0 = env.now()
    settle_sec = float(S.get("trial_dps_settle_sec", 2.0))
    meter_clean = False           # the DPS meter has read 0 since this room was cleared
    same_wave, last_wave_done = 0, None
    unreached_since = None        # first Spawn retry in the room being fought (None = none yet)
    covered_since = 0.0
    env.sleep(1.5)
    sprint_off_for_trial(env, S)
    f = env.frame()
    room = spawn_and_walk(clean=f is not None and hud.dps_hitting(f) is False)
    if room:
        last_spawn = room.spawned_at
    else:
        room = Room(env, S)
    progress_at = env.now()
    while True:
        if not env.running():
            stop_flag = getattr(env, "stop_flag", None)
            ended = "stopped" if (stop_flag and stop_flag()) else "paused"
            break
        now = env.now()
        f = env.frame()
        if f is None:
            env.sleep(0.3)
            continue
        if now - last_map > 1.5:
            last_map = now
            if hud.has_minimap(f):
                env.log("minimap seen · this is a dungeon, not a trial")
                return "dungeon"
            find = getattr(env, "find", None)
            if find and find("defheart", f):
                env.log("HEALTH counter seen · this is Defense, not a trial")
                return "defense"
        if mode != "culling" and now - last_pop > 3:
            last_pop = now
            pop = hud.find_popup(f)
            if pop and pop.kind == "dungeon":
                env.release_all()
                env.click(pop.x, pop.y)
                env.status("leaving the trial for a dungeon")
                env.log("leaving the trial for a dungeon")
                t0 = env.now()
                while env.now() - t0 < 20 and not env.has_minimap():
                    env.sleep(0.5)
                return "dungeon"
        if env.find("roomhud", f) is None:
            env.release_all()
            cov = getattr(env, "covered", None)
            if cov and cov():                   # black trait-roll screen: not the end of the
                covered_since = covered_since or now    # trial (30 s of it at most)
                if now - covered_since < 30:
                    env.sleep(0.3)
                    continue
            else:
                covered_since = 0.0
            misses += 1
            if misses >= 6:
                break                       # trial is over
            env.sleep(0.3)
            continue
        misses = 0
        if env.housekeeping():
            continue
        en, wv = hud.read_counter(f, "enemies"), hud.read_counter(f, "wave")
        en_t, wv_t = (en.text if en else "?"), (wv.text if wv else "?")
        env.info["enemies"], env.info["wave"] = en_t, wv_t
        hitting = hud.dps_hitting(f)
        if hitting:
            last_hit = now
            if room.zero and room.first_hit is None and room.walked is not None:
                room.first_hit = room.walked
        elif hitting is False:
            room.zero = True
        skill = S.get("skill_key", "")
        if skill and now - getattr(env, "_last_skill", 0) > 1.5:
            env.tap(skill)
            env._last_skill = now
        waited = now - room.start
        # progress = a real change in what the counters say. A counter that can't be read for a
        # moment ("?", e.g. a bright effect behind it) is not progress: counting it as progress
        # kept resetting the "nothing happening" timer, so the trial stood still for minutes
        # (no step further in, no Spawn) - "nothing in reach · 172s".
        if en is not None and wv is not None:
            seen = (en.a, en.b, wv.a)
            if seen != last_seen:
                last_seen, progress_at = seen, now
        quiet = now - max(progress_at, last_hit)
        respawn = float(S.get("trial_respawn_sec", 10))
        # and a hard limit per room, whatever the counters say: this long in a room with
        # nothing hit for 20 s = Spawn and walk in again
        stuck_room = waited > float(S.get("trial_room_max_sec", 90)) and now - last_hit > respawn
        if ((room.steps >= len(room.plan) and quiet > respawn) or quiet > 180 or stuck_room) \
                and now - last_spawn > respawn:
            env.log(f"trial: nothing hit for {now - last_hit if last_hit else quiet:.0f}s"
                    f" ({waited:.0f}s in this room) · pressing Spawn")
            if unreached_since is None:
                unreached_since = now
            elif room.retries == 1:
                env.shot("trial-unreachable", force=True)     # second retry: a picture of why
            # still nothing after trial_give_up_sec of retries (laptop 10-16 09:18: 12 minutes of
            # Spawn retries in wave 21 until the dungeon popup came): leave with what's been won
            give_up = float(S.get("trial_give_up_sec", 180))
            if give_up > 0 and now - unreached_since > give_up:
                c = env.find("leave", f)
                if c:
                    env.release_all()
                    env.log(f"trial: couldn't reach the enemies in wave {wv_t} for {now - unreached_since:.0f}s"
                            " · leaving the trial")
                    env.shot("trial-gave-up", force=True)
                    env.click(*c)
                    env.sleep(3)
                    ended = "gave up"
                    break
            clip = getattr(env, "clip", None)
            if clip:
                clip("trial: couldn't reach the enemies")
            r = spawn_and_walk(clean=hitting is False)
            if r:
                r.saw_fight, r.learn = False, False
                r.retries = room.retries + 1
                if r.retries >= 2:          # straight in twice and nothing: check the sides too
                    r.plan = step_plan(S, r.walked, sides=True)
                    env.log("trial: straight in didn't reach them twice · also checking the sides")
                room = r
                last_spawn, progress_at = r.spawned_at, env.now()
            else:
                # no Spawn button: pressing it again every second got nowhere (laptop 10-15,
                # "nothing hit for 118s...157s"). Search the room on foot instead - further in,
                # then a lane on each side - and try Spawn again in trial_respawn_sec.
                walked, retries = room.walked, room.retries + 1
                room = Room(env, S)
                room.retries, room.learn = retries, False
                room.plan = step_plan(S, walked, sides=True)
                last_spawn = progress_at = env.now()
            continue
        if en and en.a < en.b:
            room.saw_fight = True
        # enemies left but the DPS meter says nothing is being hit: they're out of reach.
        # Walk on straight in, letting go once damage shows up (one step at a time with a pause
        # after each if the meter can't be read).
        if en and en.b > 0 and en.a < en.b and room.steps < len(room.plan):
            wait = float(S.get("trial_step_wait_sec", 1.2) if hitting is not None
                         else S.get("trial_step_wait_blind_sec", 4))
            if now - max(last_hit, progress_at, room.last_step) > wait:
                key, ms = room.plan[room.steps]
                n = 1
                if hitting is False:
                    while room.steps + n < len(room.plan) and room.plan[room.steps + n][0] == key:
                        n += 1
                env.status(f"trial: enemies out of reach · step {KEY_NAMES[key]} ({room.steps + 1}/{len(room.plan)})")
                if hitting is False:
                    went, _, hit_at, _ = walk_in(env, n * ms / 1000, extra_sec, clean=True, key=key)
                    used = n if went * 1000 >= n * ms - 50 else min(n, int(went * 1000 // ms) + 1)
                else:
                    env.tap(key, ms)
                    went, hit_at, used = ms / 1000, None, 1
                depth_before = room.walked
                if room.walked is not None:
                    room.walked += {"w": went, "s": -went}.get(key, 0.0)
                if hit_at is not None and room.first_hit is None and depth_before is not None and key == "w":
                    room.first_hit = depth_before + hit_at
                room.steps += used
                room.last_step = env.now()
                continue
        full = en and en.b > 0 and en.a >= en.b
        empty_sec = float(S.get("trial_empty_room_sec", 5))
        cleared = full and (room.saw_fight or waited >= empty_sec + 4)
        empty = en and en.b == 0 and waited >= empty_sec
        clear_since = (clear_since or now) if (cleared or empty) else 0.0
        if not clear_since:
            meter_clean = False
        elif hitting is False:
            meter_clean = True
        # give the door a moment to open, and the DPS meter a moment to drop to 0 (then any
        # damage after Spawn is the next room's: the walk-in can stop right at the door)
        if clear_since and now - clear_since >= 0.7 and (
                meter_clean or hitting is None or now - clear_since >= 0.7 + settle_sec):
            # learn from rooms finished with only the walk-in and forward steps: walk in as far
            # as the last rooms needed, and past the first hit as far as they needed (both the
            # 3rd quartile of the last 8 rooms, so most rooms need no extra steps)
            if room.learn and room.steps <= room.lane1:
                finals = (finals + [room.walked])[-8:]
                if room.first_hit is not None:
                    extras = (extras + [max(0.0, room.walked - room.first_hit)])[-8:]
                new_in = min(max(_q3(finals), WALK_IN_RANGE[0]), WALK_IN_RANGE[1])
                new_extra = min(max(_q3(extras), 0.0), EXTRA_MAX) if extras else extra_sec
                save = getattr(env, "save_setting", None)
                if abs(new_in - walk_in_sec) >= 0.05:
                    walk_in_sec = new_in
                    if save:
                        save("trial_walk_in_sec", round(walk_in_sec, 2), quiet=True)
                if abs(new_extra - extra_sec) >= 0.05:
                    extra_sec = new_extra
                    if save:
                        save("trial_walk_extra_sec", round(extra_sec, 2), quiet=True)
            env.log(room.line(wv_t, now - cycle_t0))
            # the same wave "cleared" over and over = the picture isn't changing (frozen screen)
            same_wave = same_wave + 1 if wv_t != "?" and wv_t == last_wave_done else 0
            last_wave_done = wv_t
            if same_wave >= 4:
                env.log(f"trial: wave {wv_t} 'cleared' 5 times in a row · the screen looks frozen · stopping this trial")
                env.shot("trial-frozen", force=True)
                break
            if wv and wv.a >= leave_after:
                c = env.find("leave", f)
                if c:
                    env.click(*c)
                    env.status(f"trial: wave {wv.a} done · leaving")
                    env.log(f"trial: left after wave {wv.a}")
                    env.shot(f"trial-left-wave-{wv.a}", force=True)
                    env.sleep(3)
                    break
            env.release_all()
            old = en_t
            cycle_t0 = env.now()
            r = spawn_and_walk(old, clean=meter_clean)
            if r:
                env.status(f"trial wave {wv_t} cleared · Spawn + walk in")
                room, last_spawn = r, r.spawned_at
            else:
                env.status(f"trial wave {wv_t} cleared · walking {walk_sec:.1f}s to the next room")
                saw_new = False
                env.set_keys({"w"})
                t0 = env.now()
                while env.now() - t0 < walk_sec and env.running():
                    env.sleep(0.1)
                    e2 = env.enemies()
                    if e2 and (e2.a < e2.b or e2.text != old):
                        saw_new = True
                env.set_keys(set())
                room = Room(env, S, saw=saw_new)
            progress_at = env.now()
            clear_since = 0.0
            unreached_since = None
            continue
        reach = "hitting" if hitting else "nothing in reach" if hitting is False else "DPS unreadable"
        env.status(f"trial wave {wv_t} · enemies {en_t} · {reach} · {waited:.0f}s")
        env.sleep(0.2)
    env.release_all()
    if no_spawn_n or spot_n:
        env.log(f"trial: Spawn picture not matched {spot_n + no_spawn_n} time(s) this trial"
                f" · clicking its usual spot worked {spot_n}, didn't {no_spawn_n}")
    if abs(walk_in_sec - start_walk_in[0]) >= 0.05 or abs(extra_sec - start_walk_in[1]) >= 0.05:
        env.log(f"trial: walk-in now {walk_in_sec:.1f}s, {extra_sec:.1f}s past the first hit (learned from the last rooms)")
    return ended or "done"
