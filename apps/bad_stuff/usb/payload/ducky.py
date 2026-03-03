"""
ducky.py
Ducky Script 3.0 interpreter for Pi Gadget.
Parses and executes .ds payload files.

Supported commands:
  STRING / TYPE text       — type text
  STRINGLN text            — type text + Enter
  DELAY ms                 — wait ms milliseconds
  ENTER, TAB, SPACE        — key presses
  BACKSPACE, ESC, DELETE   — key presses
  UP, DOWN, LEFT, RIGHT    — arrow keys
  F1 ... F12               — function keys
  CAPSLOCK, NUMLOCK        — toggle keys
  PRINTSCREEN              — print screen
  MENU                     — context menu key
  HOME, END, INSERT        — navigation keys
  PAGEUP, PAGEDOWN         — page keys

  Modifier combos:
  GUI / WIN [key]          — Meta/Win key
  CTRL [key]               — Ctrl
  ALT [key]                — Alt
  SHIFT [key]              — Shift
  CTRL-ALT [key]           — Ctrl+Alt
  CTRL-SHIFT [key]         — Ctrl+Shift
  ALT-SHIFT [key]          — Alt+Shift
  GUI-SHIFT [key]          — GUI+Shift

  Variables:
  VAR $name = value        — declare variable (string or int)
  $name = value            — assign
  $name = $name + 1        — arithmetic
  $name = RANDOM_INT 1 10  — random integer
  $name = RANDOM_CHAR      — random letter a-z

  Control flow:
  IF ($cond) THEN          — condition (==, !=, <, >, <=, >=)
  ELSE IF ($cond) THEN
  ELSE
  END_IF

  WHILE ($cond)            — loop
  END_WHILE

  FUNCTION name()          — define function
  END_FUNCTION
  name()                   — call function

  Other:
  REM / # / //             — comment
  ATTACKMODE HID           — ignored (compatibility)
  SAVE_HOST_KEYBOARD_LOCK_STATE  — ignored
  RESTORE_HOST_KEYBOARD_LOCK_STATE — ignored
"""

import re
import time
import random
import struct
import os

HID_DEVICE = "/dev/hidg0"

# ── HID constants ─────────────────────────────────────────────
MOD_LCTRL  = 0x01
MOD_LSHIFT = 0x02
MOD_LALT   = 0x04
MOD_LMETA  = 0x08

_ASCII_MAP = {
    ' ':  (0x00, 0x2c), '\t': (0x00, 0x2b), '\n': (0x00, 0x28),
    'a':  (0x00, 0x04), 'b':  (0x00, 0x05), 'c':  (0x00, 0x06),
    'd':  (0x00, 0x07), 'e':  (0x00, 0x08), 'f':  (0x00, 0x09),
    'g':  (0x00, 0x0a), 'h':  (0x00, 0x0b), 'i':  (0x00, 0x0c),
    'j':  (0x00, 0x0d), 'k':  (0x00, 0x0e), 'l':  (0x00, 0x0f),
    'm':  (0x00, 0x10), 'n':  (0x00, 0x11), 'o':  (0x00, 0x12),
    'p':  (0x00, 0x13), 'q':  (0x00, 0x14), 'r':  (0x00, 0x15),
    's':  (0x00, 0x16), 't':  (0x00, 0x17), 'u':  (0x00, 0x18),
    'v':  (0x00, 0x19), 'w':  (0x00, 0x1a), 'x':  (0x00, 0x1b),
    'y':  (0x00, 0x1c), 'z':  (0x00, 0x1d),
    'A':  (0x02, 0x04), 'B':  (0x02, 0x05), 'C':  (0x02, 0x06),
    'D':  (0x02, 0x07), 'E':  (0x02, 0x08), 'F':  (0x02, 0x09),
    'G':  (0x02, 0x0a), 'H':  (0x02, 0x0b), 'I':  (0x02, 0x0c),
    'J':  (0x02, 0x0d), 'K':  (0x02, 0x0e), 'L':  (0x02, 0x0f),
    'M':  (0x02, 0x10), 'N':  (0x02, 0x11), 'O':  (0x02, 0x12),
    'P':  (0x02, 0x13), 'Q':  (0x02, 0x14), 'R':  (0x02, 0x15),
    'S':  (0x02, 0x16), 'T':  (0x02, 0x17), 'U':  (0x02, 0x18),
    'V':  (0x02, 0x19), 'W':  (0x02, 0x1a), 'X':  (0x02, 0x1b),
    'Y':  (0x02, 0x1c), 'Z':  (0x02, 0x1d),
    '1':  (0x00, 0x1e), '2':  (0x00, 0x1f), '3':  (0x00, 0x20),
    '4':  (0x00, 0x21), '5':  (0x00, 0x22), '6':  (0x00, 0x23),
    '7':  (0x00, 0x24), '8':  (0x00, 0x25), '9':  (0x00, 0x26),
    '0':  (0x00, 0x27),
    '!':  (0x02, 0x1e), '@':  (0x02, 0x1f), '#':  (0x02, 0x20),
    '$':  (0x02, 0x21), '%':  (0x02, 0x22), '^':  (0x02, 0x23),
    '&':  (0x02, 0x24), '*':  (0x02, 0x25), '(':  (0x02, 0x26),
    ')':  (0x02, 0x27), '-':  (0x00, 0x2d), '_':  (0x02, 0x2d),
    '=':  (0x00, 0x2e), '+':  (0x02, 0x2e), '[':  (0x00, 0x2f),
    '{':  (0x02, 0x2f), ']':  (0x00, 0x30), '}':  (0x02, 0x30),
    '\\': (0x00, 0x31), '|':  (0x02, 0x31), ';':  (0x00, 0x33),
    ':':  (0x02, 0x33), "'":  (0x00, 0x34), '"':  (0x02, 0x34),
    '`':  (0x00, 0x35), '~':  (0x02, 0x35), ',':  (0x00, 0x36),
    '<':  (0x02, 0x36), '.':  (0x00, 0x37), '>':  (0x02, 0x37),
    '/':  (0x00, 0x38), '?':  (0x02, 0x38),
}

_KEY_MAP = {
    "ENTER":       (0x00, 0x28), "ESC":         (0x00, 0x29),
    "ESCAPE":      (0x00, 0x29), "BACKSPACE":   (0x00, 0x2a),
    "TAB":         (0x00, 0x2b), "SPACE":       (0x00, 0x2c),
    "CAPSLOCK":    (0x00, 0x39), "F1":          (0x00, 0x3a),
    "F2":          (0x00, 0x3b), "F3":          (0x00, 0x3c),
    "F4":          (0x00, 0x3d), "F5":          (0x00, 0x3e),
    "F6":          (0x00, 0x3f), "F7":          (0x00, 0x40),
    "F8":          (0x00, 0x41), "F9":          (0x00, 0x42),
    "F10":         (0x00, 0x43), "F11":         (0x00, 0x44),
    "F12":         (0x00, 0x45), "PRINTSCREEN": (0x00, 0x46),
    "SCROLLLOCK":  (0x00, 0x47), "PAUSE":       (0x00, 0x48),
    "INSERT":      (0x00, 0x49), "HOME":        (0x00, 0x4a),
    "PAGEUP":      (0x00, 0x4b), "DELETE":      (0x00, 0x4c),
    "END":         (0x00, 0x4d), "PAGEDOWN":    (0x00, 0x4e),
    "RIGHT":       (0x00, 0x4f), "LEFT":        (0x00, 0x50),
    "DOWN":        (0x00, 0x51), "UP":          (0x00, 0x52),
    "NUMLOCK":     (0x00, 0x53), "MENU":        (0x00, 0x65),
    "APP":         (0x00, 0x65),
}

_MOD_MAP = {
    "CTRL":  MOD_LCTRL,  "CONTROL": MOD_LCTRL,
    "ALT":   MOD_LALT,   "SHIFT":   MOD_LSHIFT,
    "GUI":   MOD_LMETA,  "WIN":     MOD_LMETA,
    "WINDOWS": MOD_LMETA,
}

# Combo modifiers like CTRL-ALT, GUI-SHIFT etc.
_COMBO_MOD_MAP = {
    "CTRL-ALT":    MOD_LCTRL | MOD_LALT,
    "CTRL-SHIFT":  MOD_LCTRL | MOD_LSHIFT,
    "ALT-SHIFT":   MOD_LALT  | MOD_LSHIFT,
    "GUI-SHIFT":   MOD_LMETA | MOD_LSHIFT,
    "GUI-CTRL":    MOD_LMETA | MOD_LCTRL,
    "CTRL-ALT-SHIFT": MOD_LCTRL | MOD_LALT | MOD_LSHIFT,
}


# ── HID low-level ─────────────────────────────────────────────

def _hid_report(modifier: int, keycode: int) -> bytes:
    return struct.pack("8B", modifier, 0, keycode, 0, 0, 0, 0, 0)

_RELEASE = _hid_report(0, 0)


def _send_key(fd, modifier: int, keycode: int, delay: float = 0.02):
    fd.write(_hid_report(modifier, keycode))
    fd.flush()
    time.sleep(delay)
    fd.write(_RELEASE)
    fd.flush()
    time.sleep(delay)


def _type_string(fd, text: str):
    for ch in text:
        m = _ASCII_MAP.get(ch)
        if m:
            _send_key(fd, m[0], m[1])


# ── Tokenizer ─────────────────────────────────────────────────

def _tokenize(source: str) -> list:
    """Split source into list of (lineno, tokens) tuples."""
    lines = []
    for i, raw in enumerate(source.splitlines(), 1):
        line = raw.strip()
        # Strip comments
        if not line or line.startswith("REM ") or line.startswith("//") or line.startswith("#"):
            continue
        lines.append((i, line))
    return lines


# ── Parser → AST ──────────────────────────────────────────────

class ParseError(Exception):
    pass


def _parse(lines: list) -> list:
    """
    Parse tokenized lines into AST nodes.
    Returns list of AST node dicts.
    """
    ast   = []
    stack = [ast]  # stack of current block lists
    funcs = {}     # name → list of nodes (collected during parse)

    i = 0
    while i < len(lines):
        lineno, line = lines[i]
        node = _parse_line(lineno, line, funcs, lines)
        if node is None:
            i += 1
            continue

        if node["type"] == "IF":
            # Collect THEN body, ELSE IF, ELSE, END_IF
            branches = []  # list of (condition, body)
            else_body = None

            cond = node["cond"]
            body = []

            i += 1
            depth = 1
            while i < len(lines):
                ln, l = lines[i]
                upper = l.upper()
                if upper.startswith("IF ") or upper.startswith("IF("):
                    depth += 1
                    body.append(_parse_line(ln, l, funcs, lines))
                elif upper == "END_IF":
                    depth -= 1
                    if depth == 0:
                        branches.append((cond, body))
                        break
                    else:
                        body.append({"type": "END_IF"})
                elif upper.startswith("ELSE IF") and depth == 1:
                    branches.append((cond, body))
                    m = re.match(r'ELSE\s+IF\s*\((.+)\)\s*THEN', l, re.IGNORECASE)
                    cond = m.group(1).strip() if m else ""
                    body = []
                elif upper == "ELSE" and depth == 1:
                    branches.append((cond, body))
                    cond = None
                    body = []
                else:
                    n = _parse_line(ln, l, funcs, lines)
                    if n:
                        body.append(n)
                i += 1

            if cond is None:
                else_body = body
            else:
                branches.append((cond, body))

            stack[-1].append({"type": "IF_CHAIN", "branches": branches, "else": else_body})
            i += 1
            continue

        elif node["type"] == "WHILE":
            body = []
            i += 1
            depth = 1
            while i < len(lines):
                ln, l = lines[i]
                upper = l.upper()
                if upper.startswith("WHILE ") or upper.startswith("WHILE("):
                    depth += 1
                    body.append(_parse_line(ln, l, funcs, lines))
                elif upper == "END_WHILE":
                    depth -= 1
                    if depth == 0:
                        break
                    body.append({"type": "END_WHILE"})
                else:
                    n = _parse_line(ln, l, funcs, lines)
                    if n:
                        body.append(n)
                i += 1
            stack[-1].append({"type": "WHILE", "cond": node["cond"], "body": body})
            i += 1
            continue

        elif node["type"] == "FUNCTION_DEF":
            body = []
            i += 1
            while i < len(lines):
                ln, l = lines[i]
                if l.upper() == "END_FUNCTION":
                    break
                n = _parse_line(ln, l, funcs, lines)
                if n:
                    body.append(n)
                i += 1
            funcs[node["name"]] = body
            i += 1
            continue

        stack[-1].append(node)
        i += 1

    return ast, funcs


def _parse_line(lineno, line, funcs, lines) -> dict:
    """Parse a single line into an AST node."""
    upper = line.upper()
    parts = line.split(None, 1)
    cmd   = parts[0].upper()
    args  = parts[1] if len(parts) > 1 else ""

    # ── Ignored compatibility commands ────────────────────────
    if cmd in ("ATTACKMODE", "SAVE_HOST_KEYBOARD_LOCK_STATE",
               "RESTORE_HOST_KEYBOARD_LOCK_STATE", "LED_OFF",
               "LED_R", "LED_G", "WAIT_FOR_BUTTON_PRESS",
               "HOLD", "RELEASE"):
        return {"type": "NOP"}

    # ── Comments ───────────────────────────────────────────────
    if cmd in ("REM", "//", "#"):
        return None

    # ── Variable declaration / assignment ─────────────────────
    if cmd == "VAR":
        # VAR $name = value
        m = re.match(r'\$(\w+)\s*=\s*(.+)', args)
        if m:
            return {"type": "VAR", "name": m.group(1), "expr": m.group(2).strip()}
        return {"type": "NOP"}

    if line.startswith("$"):
        # $name = expr
        m = re.match(r'\$(\w+)\s*=\s*(.+)', line)
        if m:
            return {"type": "ASSIGN", "name": m.group(1), "expr": m.group(2).strip()}
        return {"type": "NOP"}

    # ── Control flow ───────────────────────────────────────────
    if cmd == "IF":
        m = re.match(r'IF\s*\((.+)\)\s*THEN', line, re.IGNORECASE)
        cond = m.group(1).strip() if m else args
        return {"type": "IF", "cond": cond}

    if cmd == "WHILE":
        m = re.match(r'WHILE\s*\((.+)\)', line, re.IGNORECASE)
        cond = m.group(1).strip() if m else args
        return {"type": "WHILE", "cond": cond}

    if upper == "END_IF":
        return {"type": "END_IF"}

    if upper == "END_WHILE":
        return {"type": "END_WHILE"}

    if upper == "BREAK":
        return {"type": "BREAK"}

    # ── Function definition ────────────────────────────────────
    if cmd == "FUNCTION":
        name = args.replace("()", "").strip()
        return {"type": "FUNCTION_DEF", "name": name}

    if upper == "END_FUNCTION":
        return {"type": "END_FUNCTION"}

    # ── Function call: name() ──────────────────────────────────
    if line.endswith("()") and re.match(r'^\w+\(\)$', line):
        return {"type": "CALL", "name": line[:-2]}

    # ── Typing ────────────────────────────────────────────────
    if cmd in ("STRING", "TYPE"):
        return {"type": "STRING", "text": args}

    if cmd == "STRINGLN":
        return {"type": "STRINGLN", "text": args}

    # ── Delay ─────────────────────────────────────────────────
    if cmd == "DELAY":
        return {"type": "DELAY", "ms": args}

    if cmd == "DEFAULT_DELAY" or cmd == "DEFAULTDELAY":
        return {"type": "DEFAULT_DELAY", "ms": args}

    # ── Simple keys ───────────────────────────────────────────
    if cmd in _KEY_MAP:
        return {"type": "KEY", "mod": 0x00, "key": cmd}

    # ── Modifier + optional key ───────────────────────────────
    # Check combo modifiers first (CTRL-ALT, GUI-SHIFT etc.)
    for combo, mod_val in _COMBO_MOD_MAP.items():
        if upper.startswith(combo):
            rest = line[len(combo):].strip().upper()
            return {"type": "KEY", "mod": mod_val, "key": rest or None}

    # Single modifiers
    if cmd in _MOD_MAP:
        rest = args.upper().strip()
        return {"type": "KEY", "mod": _MOD_MAP[cmd], "key": rest or None}

    return {"type": "NOP"}


# ── Interpreter ───────────────────────────────────────────────

class DuckyInterpreter:
    def __init__(self, status_cb=None):
        self.status_cb    = status_cb  # called with status string during execution
        self.variables    = {}
        self.functions    = {}
        self.default_delay = 0
        self._fd          = None
        self._break       = False

    def execute_file(self, path: str) -> tuple:
        """Execute a .ds file. Returns (ok, message)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as e:
            return False, f"Cannot read file: {e}"

        if not os.path.exists(HID_DEVICE):
            return False, "HID not available.\nEnable keyboard mode\nin USB settings."

        try:
            self._fd = open(HID_DEVICE, "wb")
        except PermissionError:
            return False, "Permission denied.\nAdd user to input group."
        except Exception as e:
            return False, str(e)[:50]

        try:
            lines = _tokenize(source)
            ast, funcs = _parse(lines)
            self.functions = funcs
            self._exec_block(ast)
            self._fd.write(_RELEASE)
            self._fd.flush()
            self._fd.close()
            return True, "Payload executed\nsuccessfully"
        except Exception as e:
            try:
                self._fd.close()
            except Exception:
                pass
            return False, str(e)[:60]

    def _exec_block(self, nodes: list):
        """Execute a list of AST nodes."""
        for node in nodes:
            if self._break:
                break
            self._exec_node(node)

    def _exec_node(self, node: dict):
        t = node["type"]

        if t == "NOP":
            pass

        elif t in ("VAR", "ASSIGN"):
            val = self._eval_expr(node["expr"])
            self.variables[node["name"]] = val

        elif t == "STRING":
            text = self._interpolate(node["text"])
            if self.status_cb:
                self.status_cb(f"TYPE: {text[:20]}")
            _type_string(self._fd, text)
            if self.default_delay:
                time.sleep(self.default_delay / 1000.0)

        elif t == "STRINGLN":
            text = self._interpolate(node["text"])
            _type_string(self._fd, text)
            _send_key(self._fd, 0x00, 0x28)
            if self.default_delay:
                time.sleep(self.default_delay / 1000.0)

        elif t == "DELAY":
            ms = self._eval_expr(node["ms"])
            try:
                time.sleep(float(ms) / 1000.0)
            except (ValueError, TypeError):
                pass

        elif t == "DEFAULT_DELAY":
            try:
                self.default_delay = int(self._eval_expr(node["ms"]))
            except (ValueError, TypeError):
                pass

        elif t == "KEY":
            mod = node["mod"]
            key = node["key"]
            if key and key in _KEY_MAP:
                kc = _KEY_MAP[key][1]
                _send_key(self._fd, mod, kc)
            elif key and len(key) == 1:
                m = _ASCII_MAP.get(key.lower())
                if m:
                    _send_key(self._fd, mod | m[0], m[1])
            elif mod:
                _send_key(self._fd, mod, 0x00)
            if self.default_delay:
                time.sleep(self.default_delay / 1000.0)

        elif t == "IF_CHAIN":
            executed = False
            for cond, body in node["branches"]:
                if self._eval_cond(cond):
                    self._exec_block(body)
                    executed = True
                    break
            if not executed and node.get("else"):
                self._exec_block(node["else"])

        elif t == "WHILE":
            max_iter = 100000
            i = 0
            while self._eval_cond(node["cond"]) and i < max_iter:
                self._break = False
                self._exec_block(node["body"])
                if self._break:
                    self._break = False
                    break
                i += 1

        elif t == "BREAK":
            self._break = True

        elif t == "CALL":
            fname = node["name"]
            if fname in self.functions:
                if self.status_cb:
                    self.status_cb(f"CALL {fname}()")
                self._exec_block(self.functions[fname])

    # ── Expression evaluator ──────────────────────────────────

    def _eval_expr(self, expr: str):
        """Evaluate an expression string. Returns int or str."""
        expr = expr.strip()

        # RANDOM_INT min max
        m = re.match(r'RANDOM_INT\s+(\d+)\s+(\d+)', expr, re.IGNORECASE)
        if m:
            return random.randint(int(m.group(1)), int(m.group(2)))

        # RANDOM_CHAR
        if expr.upper() == "RANDOM_CHAR":
            return random.choice("abcdefghijklmnopqrstuvwxyz")

        # Arithmetic: $x + 1, $x - 1, $x * 2
        m = re.match(r'\$(\w+)\s*([+\-*/])\s*(.+)', expr)
        if m:
            left  = self.variables.get(m.group(1), 0)
            op    = m.group(2)
            right = self._eval_expr(m.group(3))
            try:
                left  = int(left)
                right = int(right)
                if op == "+": return left + right
                if op == "-": return left - right
                if op == "*": return left * right
                if op == "/" and right != 0: return left // right
            except (ValueError, TypeError):
                if op == "+": return str(left) + str(right)
            return left

        # Variable reference
        if expr.startswith("$"):
            return self.variables.get(expr[1:], "")

        # Quoted string
        if (expr.startswith('"') and expr.endswith('"')) or \
           (expr.startswith("'") and expr.endswith("'")):
            return expr[1:-1]

        # Integer literal
        try:
            return int(expr)
        except ValueError:
            pass

        return expr

    def _interpolate(self, text: str) -> str:
        """Replace $variables in text with their values."""
        def replace(m):
            return str(self.variables.get(m.group(1), ""))
        return re.sub(r'\$(\w+)', replace, text)

    def _eval_cond(self, cond: str) -> bool:
        """Evaluate a condition string like '$x == 5' or '$x < 10'."""
        if cond is None:
            return True
        cond = cond.strip()

        ops = [("==", lambda a, b: a == b),
               ("!=", lambda a, b: a != b),
               ("<=", lambda a, b: _num(a) <= _num(b)),
               (">=", lambda a, b: _num(a) >= _num(b)),
               ("<",  lambda a, b: _num(a) <  _num(b)),
               (">",  lambda a, b: _num(a) >  _num(b))]

        for op_str, fn in ops:
            if op_str in cond:
                parts = cond.split(op_str, 1)
                left  = self._eval_expr(parts[0].strip())
                right = self._eval_expr(parts[1].strip())
                try:
                    return fn(left, right)
                except Exception:
                    return False

        # Boolean variable
        val = self._eval_expr(cond)
        return bool(val) and val not in (0, "0", "false", "FALSE", "")


def _num(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


# ── Public API ────────────────────────────────────────────────

def execute(path: str, status_cb=None) -> tuple:
    """Execute a Ducky Script 3.0 file. Returns (ok, message)."""
    interp = DuckyInterpreter(status_cb=status_cb)
    return interp.execute_file(path)
