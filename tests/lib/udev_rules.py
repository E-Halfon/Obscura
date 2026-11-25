"""A minimal udev rules evaluator for Camera Obscura's capability rules (task 0.2c).

It evaluates one rules file against one recorded event, the way systemd-udevd would,
for the subset of the rules language the capability rules use:

    match       ACTION  SUBSYSTEM  KERNEL  DEVPATH  ENV{key}  ATTR{file} (== and !=)
    parent      DRIVERS  KERNELS  SUBSYSTEMS  ATTRS{file}              (== and !=)
    assign      TAG+=  ENV{key}=  ENV{key}+=
    control     GOTO=  LABEL=

Anything else (another key, :=, -=, an operator a key doesn't take) raises UnsupportedRule,
so a rule can't grow syntax that the tests silently ignore.

Semantics followed (systemd's udev-rules.c and udev(7)):
- Patterns are shell globs (*, ?, [...]) with "|" separating alternatives. A missing
  property matches as the empty string.
- **Parent keys on one line must all match the same device:** udev walks from the event's
  device up through its parents and stops at the first one that satisfies every parent key
  of the line. The device itself is the first candidate. A negated parent key holds for a
  device whose value doesn't match.
- ATTR and ATTRS values have trailing whitespace removed before matching, and an attribute
  file that doesn't exist never matches, not even negated. ATTR reads the event's device,
  the first entry of parents.
- Assignments run in line order once every match key of the line held; GOTO then jumps to
  its LABEL. ENV{key}+= appends with a space, as SYSTEMD_WANTS uses it.

An event is a dict (see event_from_record): action, devpath, kernel, subsystem, env, and
parents, a list from the device itself upwards of {kernel, subsystem, driver, attrs}.

Test helper (tests/ is exempt from the production try/except rule): malformed input raises.
"""

import fnmatch
import re

MATCH_KEYS = frozenset({"ACTION", "SUBSYSTEM", "KERNEL", "DEVPATH", "ENV", "ATTR"})
PARENT_KEYS = frozenset({"DRIVERS", "KERNELS", "SUBSYSTEMS", "ATTRS"})
ASSIGN_KEYS = frozenset({"TAG", "ENV", "GOTO", "LABEL"})
KEYS_WITH_ATTRIBUTE = frozenset({"ENV", "ATTR", "ATTRS"})

TOKEN = re.compile(
    r'\s*(?P<key>[A-Z_]+)(?:\{(?P<attr>[^}]*)\})?\s*(?P<op>==|!=|\+=|-=|:=|=)\s*"(?P<value>(?:[^"\\]|\\.)*)"\s*(?:,|$)')


class UnsupportedRule(Exception):
    """The rules file uses syntax this evaluator doesn't model."""


class Rule:
    """One rule line: its tokens, split into matches, parent matches and actions."""

    def __init__(self, number, text, tokens):
        self.number = number
        self.text = text
        self.matches = [t for t in tokens if t[2] in ("==", "!=") and t[0] not in PARENT_KEYS]
        self.parent_matches = [t for t in tokens if t[0] in PARENT_KEYS]
        self.actions = [t for t in tokens if t[2] not in ("==", "!=")]


def logical_lines(text):
    """(first line number, text) per rule, with backslash continuations joined and comments
    and blank lines dropped."""
    lines = []
    pending, start = "", None
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        if start is None:
            start = number
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        lines.append((start, pending + stripped))
        pending, start = "", None
    if pending:
        raise UnsupportedRule("line " + str(start) + ": continuation at end of file")
    return lines


def parse_line(number, line):
    """[(key, attr, op, value)] for one logical line. Raises UnsupportedRule."""
    tokens, position = [], 0
    while position < len(line):
        match = TOKEN.match(line, position)
        if not match or match.end() == position:
            raise UnsupportedRule("line " + str(number) + ": can't parse at: " + line[position:])
        key, attr, op, value = match.group("key", "attr", "op", "value")
        if (attr is not None) != (key in KEYS_WITH_ATTRIBUTE):
            raise UnsupportedRule("line " + str(number) + ": " + key + " attribute use not supported")
        if op in ("==", "!="):
            if key not in MATCH_KEYS and key not in PARENT_KEYS:
                raise UnsupportedRule("line " + str(number) + ": match key " + key + " not supported")
        elif op in ("=", "+="):
            if key not in ASSIGN_KEYS or key in PARENT_KEYS:
                raise UnsupportedRule("line " + str(number) + ": assignment to " + key + " not supported")
            if key in ("GOTO", "LABEL") and op != "=":
                raise UnsupportedRule("line " + str(number) + ": " + key + " takes only =")
            if key == "TAG" and op != "+=":
                raise UnsupportedRule("line " + str(number) + ": TAG takes only += here")
        else:
            raise UnsupportedRule("line " + str(number) + ": operator " + op + " not supported")
        tokens.append((key, attr, op, value.replace('\\"', '"')))
        position = match.end()
    if not tokens:
        raise UnsupportedRule("line " + str(number) + ": empty rule")
    labels = [t for t in tokens if t[0] == "LABEL"]
    if labels and len(tokens) != 1:
        raise UnsupportedRule("line " + str(number) + ": LABEL must stand alone here")
    return tokens


def parse(text):
    """[Rule] for a rules file's text. Raises UnsupportedRule."""
    rules = [Rule(number, line, parse_line(number, line)) for number, line in logical_lines(text)]
    labels = {}
    for index, rule in enumerate(rules):
        for key, _, _, value in rule.actions:
            if key == "LABEL":
                labels[value] = index
    for index, rule in enumerate(rules):
        for key, _, _, value in rule.actions:
            if key == "GOTO" and labels.get(value, -1) <= index:
                raise UnsupportedRule("line " + str(rule.number) + ": GOTO " + value + " has no later LABEL")
    return rules


def glob_matches(pattern, value):
    """udev's pattern match: shell glob, "|" separates alternatives."""
    value = "" if value is None else str(value)
    return any(fnmatch.fnmatchcase(value, alternative) for alternative in pattern.split("|"))


def holds(op, pattern, value):
    matched = glob_matches(pattern, value)
    return matched if op == "==" else not matched


def device_value(event, key, attr):
    if key == "ACTION":
        return event["action"]
    if key == "SUBSYSTEM":
        return event["subsystem"]
    if key == "KERNEL":
        return event["kernel"]
    if key == "DEVPATH":
        return event["devpath"]
    if key == "ENV":
        return event["env"].get(attr, "")
    if key == "ATTR":
        device = event["parents"][0] if event["parents"] else {}
        return parent_value(device, "ATTRS", attr)
    raise UnsupportedRule("no value for " + key)


def device_holds(event, token):
    key, attr, op, pattern = token
    value = device_value(event, key, attr)
    if key == "ATTR" and value is None:
        return False
    return holds(op, pattern, value)


def parent_value(parent, key, attr):
    if key == "DRIVERS":
        return parent.get("driver") or ""
    if key == "KERNELS":
        return parent.get("kernel") or ""
    if key == "SUBSYSTEMS":
        return parent.get("subsystem") or ""
    if key == "ATTRS":
        value = (parent.get("attrs") or {}).get(attr)
        return None if value is None else value.rstrip()
    raise UnsupportedRule("no parent value for " + key)


def parents_match(event, parent_tokens):
    """True if one device in the chain (the device first) satisfies every parent key."""
    if not parent_tokens:
        return True
    for parent in event["parents"]:
        ok = True
        for key, attr, op, pattern in parent_tokens:
            value = parent_value(parent, key, attr)
            if key == "ATTRS" and value is None:
                # udev: a missing attribute file never matches, not even negated.
                ok = False
                break
            if not holds(op, pattern, value):
                ok = False
                break
        if ok:
            return True
    return False


def evaluate(rules, event):
    """{'tags': set, 'env': dict, 'trace': [rule numbers that matched]} after running
    `rules` (from parse) on `event`. env starts from the event's env and gets assignments."""
    env = dict(event["env"])
    tags = set()
    trace = []
    working = dict(event, env=env)
    index = 0
    while index < len(rules):
        rule = rules[index]
        if all(device_holds(working, token) for token in rule.matches) \
                and parents_match(working, rule.parent_matches):
            trace.append(rule.number)
            jump = None
            for key, attr, op, value in rule.actions:
                if key == "TAG":
                    tags.add(value)
                elif key == "ENV" and op == "=":
                    env[attr] = value
                elif key == "ENV" and op == "+=":
                    env[attr] = (env[attr] + " " + value) if env.get(attr) else value
                elif key == "GOTO":
                    jump = value
            if jump is not None:
                index = next(i for i, r in enumerate(rules)
                             if any(k == "LABEL" and v == jump for k, _, _, v in r.actions))
                continue
        index += 1
    return {"tags": tags, "env": env, "trace": trace}


def wants(result, unit):
    """True if PID 1 would pull in `unit` for this device: systemd tag and SYSTEMD_WANTS."""
    return "systemd" in result["tags"] and unit in result["env"].get("SYSTEMD_WANTS", "").split()


def event_from_record(record, action=None):
    """An event dict from a fixture record (tests/fixtures/v4l/capture.py). The env is the
    recorded udev properties with the fresh v4l_id output laid over them: an event sees
    what 60-persistent-v4l.rules just imported, not the database's older value."""
    env = dict(record["properties"])
    env.update(record.get("fresh") or {})
    env["DEVPATH"] = record["devpath"]
    env["SUBSYSTEM"] = record["subsystem"]
    return {
        "action": action or record["action"],
        "devpath": record["devpath"],
        "kernel": record["kernel"],
        "subsystem": record["subsystem"],
        "env": env,
        "parents": record["parents"],
    }


def evaluate_file(path, event):
    with open(path, "r", encoding="utf-8") as handle:
        return evaluate(parse(handle.read()), event)
