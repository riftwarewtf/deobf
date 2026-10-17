"""
Static helper: maps every Luraph interpreter dispatch loop to its opcode
handlers (opcode -> handler source) using luau-ast's JSON output.

Usage: python obfuscators/luraph_v15/vmmap.py <protected.luau> [dispatch_index] [opcode...]
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))     # deobf/ (bin/luau-ast)


def load_ast(path):
    exe = os.path.join(ROOT, "bin", "luau-ast.exe" if os.name == "nt" else "luau-ast")
    r = subprocess.run([exe, path], capture_output=True)
    errs = r.stderr.decode("latin-1").strip().splitlines()
    if r.returncode != 0 or (errs and errs[0].startswith("Parse errors")):
        raise SyntaxError("not valid Luau (%s)" % (errs[1].strip() if len(errs) > 1 else "luau-ast exit %#x"
                                                   % (r.returncode & 0xFFFFFFFF)))
    out = r.stdout
    return json.loads(out.decode("latin-1"))["root"]


def loc(node):
    a, b = node["location"].split(" - ")
    l1, c1 = map(int, a.split(","))
    l2, c2 = map(int, b.split(","))
    return l1, c1, l2, c2


def text_of(lines, node):
    l1, c1, l2, c2 = loc(node)
    if l1 == l2:
        return lines[l1][c1:c2]
    parts = [lines[l1][c1:]] + lines[l1 + 1:l2] + [lines[l2][:c2]]
    return "\n".join(parts)


def walk(node, fn):
    if isinstance(node, dict):
        fn(node)
        for v in node.values():
            walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            walk(v, fn)


def local_name(expr):
    if expr.get("type") == "AstExprLocal":
        return expr["local"]["name"]
    return None


def _unwrap(e):
    """Strip parentheses: `local y = (V[W])` is the same fetch as `V[W]`."""
    while e.get("type") == "AstExprGroup":
        e = e["expr"]
    return e


def _loop_body(n):
    """(statements, form) of an endless loop, or None: `while true do ... end`
    and `repeat ... until false` are the same dispatch loop."""
    t = n.get("type")
    if t == "AstStatWhile":
        cond = n["condition"]
        if cond.get("type") != "AstExprConstantBool" or not cond.get("value"):
            return None
        return n["body"]["body"], "while"
    if t == "AstStatRepeat":
        cond = n["condition"]
        if cond.get("type") != "AstExprConstantBool" or cond.get("value"):
            return None
        body = n.get("body")
        if not isinstance(body, dict):
            return None
        return body["body"], "repeat"
    return None


# Textual form of the dispatch heads find_dispatchers recognizes, for the
# passes that patch the source rather than read the AST (driver.patch_spin).
# It matches the head only, with no groups: which target holds the opcode
# cannot be told apart textually (`local op,x=ARR[PC]` sets x to nil, while
# `local t,op=v,ARR[PC]` puts it second), so names come from the AST. A head
# this misses leaves a whole dispatch mode unpatched, so it accepts every
# form: an optional pc save in front, a parenthesized fetch, plain values
# before the fetch, and `repeat` as well as `while true do`.
_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
DISPATCH_HEAD = (
    r"(?:while true do|repeat) "
    r"(?:%(n)s\[\d+\]=%(n)s;\s*)?"                      # d[2349588]=s;
    r"(?:local )?%(n)s(?:,%(n)s)*="                     # local op,x= / op=
    r"(?:%(n)s,)*"                                      # local t,op=v,ARR[PC]
    r"\(?%(n)s\[%(n)s\]\)?;?"                           # (ARR[PC]);
    r"(?=\s*(?:if|local)\b)"                            # the if-tree follows
) % {"n": _NAME}


def find_dispatchers(root):
    """Every VM dispatch loop: an endless loop (`while true do`, `repeat ...
    until false`) that reads the opcode out of an array and branches on it,
    `local op = ARR[PC]; if-tree ... end`.

    The fetch head varies: it may be parenthesized (`local y=(V[W])`), use a
    multi-variable local whose other targets are set to nil (`local op,x=
    ARR[PC]`, `local TJ,H=q,w[s]`), be a plain assignment to a local the VM
    function declared (`op = ARR[PC]`), or follow a statement that saves the
    pc (`d[2349588]=s; local o=w[s]`). The if-tree may also start behind a
    boolean local that holds the first compare (`local op = ARR[PC]; local b
    = op <= 48; if b then ...`): v15.1 writes most of its trees that way, and
    `resolve` follows those locals.
    """
    found = []

    def visit(n):
        loop = _loop_body(n)
        if loop is None:
            return
        body, form = loop
        if len(body) < 2:
            return
        # the fetch is the first statement, or the second behind a pc save
        for idx in (0, 1):
            if idx >= len(body) - 1:
                break
            st = body[idx]
            if st["type"] not in ("AstStatLocal", "AstStatAssign"):
                continue
            for vr, vl in zip(st.get("vars") or [], st.get("values") or []):
                v = _unwrap(vl)
                if v.get("type") != "AstExprIndexExpr":
                    continue
                arr, pc = local_name(_unwrap(v["expr"])), local_name(_unwrap(v["index"]))
                if not arr or not pc:
                    continue
                opname = vr["name"] if st["type"] == "AstStatLocal" else local_name(vr)
                if not opname:
                    continue
                nxt = body[idx + 1]
                if nxt["type"] == "AstStatIf":
                    found.append({"node": n, "op": opname, "arr": arr, "pc": pc, "tree": nxt,
                                  "rest": body[idx + 2:], "form": form})
                    return
                # boolean local in between: the tree starts at the loop body,
                # so resolve() sees the local's definition and its `if`
                if idx + 2 < len(body) and nxt["type"] in ("AstStatLocal", "AstStatAssign") \
                        and body[idx + 2]["type"] == "AstStatIf" and len(nxt.get("values") or []) == 1:
                    v1 = _unwrap(nxt["values"][0])
                    if v1.get("type") == "AstExprBinary" and v1.get("op") in OPS:
                        found.append({"node": n, "op": opname, "arr": arr, "pc": pc,
                                      "tree": {"type": "AstStatBlock", "body": body[idx + 1:idx + 3],
                                               "location": n["location"]},
                                      "rest": body[idx + 3:], "form": form})
                        return

    walk(root, visit)
    return found


OPS = {"CompareLt": lambda a, b: a < b, "CompareLe": lambda a, b: a <= b,
       "CompareGt": lambda a, b: a > b, "CompareGe": lambda a, b: a >= b,
       "CompareEq": lambda a, b: a == b, "CompareNe": lambda a, b: a != b}
FLIP = {"CompareLt": "CompareGt", "CompareLe": "CompareGe", "CompareGt": "CompareLt",
        "CompareGe": "CompareLe", "CompareEq": "CompareEq", "CompareNe": "CompareNe"}


def eval_cond(cond, var, value):
    """Evaluate `var <op> const` for a concrete opcode value; None if not such a test."""
    cond = _unwrap(cond)
    if cond["type"] != "AstExprBinary" or cond["op"] not in OPS:
        return None
    l, r = _unwrap(cond["left"]), _unwrap(cond["right"])
    op = cond["op"]
    if local_name(l) == var and r["type"] == "AstExprConstantNumber":
        return OPS[op](value, r["value"])
    if local_name(r) == var and l["type"] == "AstExprConstantNumber":
        return OPS[FLIP[op]](value, l["value"])
    return None


def _bool_local(st, nxt, var, value, benv):
    """`local b = op <= 48` (or an assignment) followed by `if b then`: the
    compare's value for this opcode, remembered under b's name. v15.1 writes
    almost every level of its dispatch tree this way. (name, result) or None."""
    if st["type"] not in ("AstStatLocal", "AstStatAssign") or len(st.get("values") or []) != 1:
        return None
    if nxt["type"] != "AstStatIf":
        return None
    r = eval_cond(st["values"][0], var, value)
    if r is None:
        return None
    vr = st["vars"][0]
    name = vr["name"] if st["type"] == "AstStatLocal" else local_name(vr)
    if not name or local_name(_unwrap(nxt["condition"])) != name:
        return None
    benv[name] = r
    return name, r


def resolve(tree, var, value):
    """Follow the if-tree for one opcode value and return the handler block."""
    node = tree
    benv = {}       # boolean locals holding a compare of the opcode
    while True:
        if node["type"] == "AstStatBlock":
            b = node["body"]
            if len(b) >= 1 and b[0]["type"] == "AstStatIf" \
                    and eval_cond(b[0]["condition"], var, value) is not None:
                node = b[0]
                continue
            for i in range(len(b) - 1):
                if _bool_local(b[i], b[i + 1], var, value, benv):
                    node = b[i + 1]
                    break
            else:
                return node
            continue
        if node["type"] == "AstStatIf":
            r = eval_cond(node["condition"], var, value)
            if r is None:
                r = benv.get(local_name(_unwrap(node["condition"])))
                if r is None:
                    return node
            if r:
                node = node["thenbody"]
            else:
                e = node.get("elsebody")
                if e is None:
                    return None
                node = e
            continue
        return node


def handler_map(disp, lines, max_op=256):
    handlers = {}
    for op in range(max_op):
        blk = resolve(disp["tree"], disp["op"], op)
        if blk is None:
            continue
        key = blk["location"]
        handlers.setdefault(key, {"ops": [], "node": blk})["ops"].append(op)
    return handlers


def main():
    path = sys.argv[1]
    root = load_ast(path)
    with open(path, encoding="latin-1") as f:
        lines = f.read().split("\n")
    disps = find_dispatchers(root)
    if len(sys.argv) == 2:
        for i, d in enumerate(disps, 1):
            h = handler_map(d, lines)
            print("dispatch %d: op=%s arr=%s pc=%s handlers=%d at %s" % (i, d["op"], d["arr"], d["pc"], len(h),
                                                                        d["node"]["location"]))
        return
    d = disps[int(sys.argv[2]) - 1]
    want = set(int(x) for x in sys.argv[3:])
    for op in sorted(want):
        blk = resolve(d["tree"], d["op"], op)
        print("---- op %d" % op)
        print(text_of(lines, blk) if blk else "<none>")


if __name__ == "__main__":
    main()


def instrument(src, disp_index, probes, root=None, tmp_path=None):
    """Insert Lua code at the start of chosen opcode handlers of one dispatch loop.

    probes: {opcode: "lua code"}; returns modified source. Only single-line
    sources (like Luraph output) are supported.
    """
    lines = src.split("\n")
    if root is None:
        root = load_ast(tmp_path)
    d = find_dispatchers(root)[disp_index - 1]
    inserts = []
    for op, code in probes.items():
        blk = resolve(d["tree"], d["op"], op)
        if blk is None:
            continue
        l1, c1, _, _ = loc(blk)
        # block location starts right at the handler's first statement
        inserts.append((l1, c1, code))
    for l1, c1, code in sorted(inserts, reverse=True):
        s = lines[l1]
        lines[l1] = s[:c1] + " " + code + " " + s[c1:]
    return "\n".join(lines)


def instrument_post(src, disp_index, root, make_code, reg="Z", pc="W"):
    """Append logging after simple `REG[..]=...` handlers. make_code(op, dest_expr) -> lua."""
    import re as _re
    lines = src.split("\n")
    d = find_dispatchers(root)[disp_index - 1]
    h = handler_map(d, lines)
    inserts = []
    for key, v in h.items():
        blk = v["node"]
        text = text_of(lines, blk)
        if (pc + "=") in text.replace(pc + "==", "") or "return" in text or "break" in text \
                or (pc + "+=") in text or (pc + "-=") in text:
            continue
        m = _re.match(r"\s*(" + reg + r"\[[A-Za-z_]+\[" + pc + r"\]\])=", text)
        if not m:
            continue
        l1, c1, l2, c2 = loc(blk)
        inserts.append((l2, c2, make_code(v["ops"][0], m.group(1))))
    for l2, c2, code in sorted(inserts, reverse=True):
        s = lines[l2]
        lines[l2] = s[:c2] + " " + code + " " + s[c2:]
    return "\n".join(lines)


def loop_names(disp):
    """(register array, pc variable) used by a dispatch loop's handlers."""
    return ("Z", "W") if disp["pc"] == "W" else ("l", "O")


def post_inserts(src_lines, disp, make_code):
    import re as _re
    reg, pc = loop_names(disp)
    out = []
    for v in handler_map(disp, src_lines).values():
        text = text_of(src_lines, v["node"])
        if (pc + "=") in text.replace(pc + "==", "") or "return" in text or "break" in text \
                or (pc + "+=") in text or (pc + "-=") in text:
            continue
        m = _re.match(r"\s*(" + reg + r"\[[A-Za-z_]+\[" + pc + r"\]\])=", text)
        if not m:
            continue
        l1, c1, l2, c2 = loc(v["node"])
        out.append((l2, c2, make_code(v["ops"][0], m.group(1), pc)))
    return out


def instrument_everything(src, root, make_post, make_loop):
    """Post-log simple handlers in every loop and log each dispatched instruction."""
    import re as _re
    lines = src.split("\n")
    inserts = []
    for d in find_dispatchers(root):
        inserts += post_inserts(lines, d, make_post)
    for l2, c2, code in sorted(inserts, reverse=True):
        s = lines[l2]
        lines[l2] = s[:c2] + " " + code + " " + s[c2:]
    out = "\n".join(lines)
    k = [0]

    def rep(m):
        k[0] += 1
        return m.group(0) + make_loop(k[0], m.group(1), m.group(3))
    return _re.sub(r"while true do (?:local )?([A-Za-z_]+)(?:,[A-Za-z_]+)*=([A-Za-z_]+)\[([A-Za-z_]+)\];", rep, out)


def _vm_stack_idx(stack):
    """Index of the VM interpreter closure in an enclosing-function stack.
    Normally the innermost function, but a curried maker ends in two nested
    vararg closures (`return function(...) return function(...) <dispatch>`)
    and then the dispatch sits in the outer of the two."""
    if len(stack) >= 2 and stack[-1].get("vararg") and not stack[-1].get("args") \
            and stack[-2].get("vararg") and not stack[-2].get("args"):
        return len(stack) - 2
    return len(stack) - 1


def _curried3_of(stack, vm_idx):
    """v15.1's curried closure maker: three nested functions, each returning
    the next, with the dispatch loop in the innermost one
    (`function(A,H,t,...) ... return function(K,K) ... return function(...)
    <dispatch> end end end`). The proto's data is in the outermost
    function's parameters, and the closure is returned rather than stored,
    so the maker-assign hook has nothing to match. {"f3", "f2", "f1",
    "retStmt", "kind": "anon"|"named" (+ "f2Ret", "uName", "zName")}, or
    None if the stack is not that shape."""
    if vm_idx < 2:
        return None
    f3, f2, f1 = stack[vm_idx - 2], stack[vm_idx - 1], stack[vm_idx]
    f3b = (f3.get("body") or {}).get("body") or []
    ret = f3b[-1] if f3b else None
    if len(f3.get("args") or []) < 5 or not ret or ret.get("type") != "AstStatReturn":
        return None
    rlist = ret.get("list") or []
    if len(rlist) != 1:
        return None
    if _unwrap(rlist[0]) is f2:
        return {"f3": f3, "f2": f2, "f1": f1, "retStmt": ret, "kind": "anon"}
    # `local u = function(K,K) ... end; return u`: the closures are named, so
    # the hooks go on the two return statements instead of around the values
    u_name = local_name(_unwrap(rlist[0]))
    f2b = (f2.get("body") or {}).get("body") or []
    f2_ret = f2b[-1] if f2b else None
    f2_rlist = (f2_ret.get("list") or []) if f2_ret and f2_ret.get("type") == "AstStatReturn" else []
    z_name = local_name(_unwrap(f2_rlist[0])) if len(f2_rlist) == 1 else None
    if u_name and z_name:
        return {"f3": f3, "f2": f2, "f1": f1, "retStmt": ret, "f2Ret": f2_ret,
                "uName": u_name, "zName": z_name, "kind": "named"}
    return None


def closure_entries(root):
    """For each VM interpreter closure: (line, col of its first statement, proto variable name)."""
    disp_nodes = [d["node"] for d in find_dispatchers(root)]
    seen = {}

    def walk(n, stack):
        if isinstance(n, dict):
            if n.get("type") == "AstExprFunction":
                stack = stack + [n]
            if _loop_body(n) is not None and any(n is d for d in disp_nodes):
                vm_idx = _vm_stack_idx(stack)
                inner = stack[vm_idx]
                if not (inner.get("vararg") and not inner["args"]):
                    inner = next((f for f in reversed(stack) if f.get("vararg") and not f["args"]), None)
                outer = next((f for f in reversed(stack) if len(f["args"]) >= 2), None)
                if inner is None or outer is None:
                    return
                l1, c1, _, _ = loc(inner["body"]["body"][0])
                # keyed by the proto parameter: parameter 1 is not always the
                # proto (function(g, upvals, proto, ...)), and an upvalue list
                # can be shared or false, which would merge protos. A curried
                # maker has no proto parameter; the hook there numbers protos
                # by the table the capture hook builds (driver.patch_entries).
                seen[(l1, c1)] = "__pv" if _curried3_of(stack, vm_idx) \
                    else outer["args"][_maker_params(outer)[0]]["name"]
            for v in n.values():
                walk(v, stack)
        elif isinstance(n, list):
            for v in n:
                walk(v, stack)
    walk(root, [])
    return [(l, c, name) for (l, c), name in seen.items()]


def closure_makers(root):
    """For each VM closure template: (line, col just after the statement that
    stores the new closure in a local, that local's name, proto variable name).
    Luraph builds every closure of a proto with `S, h = n, function(...) ... end`
    inside a maker function whose second parameter is the proto."""
    disp_nodes = [d["node"] for d in find_dispatchers(root)]
    seen = {}

    def walk(n, stack, stmts):
        if isinstance(n, dict):
            t = n.get("type")
            if t == "AstExprFunction":
                stack = stack + [n]
            if t and t.startswith("AstStat"):
                stmts = stmts + [(n, len(stack))]
            if t == "AstStatWhile" and any(n is d for d in disp_nodes):
                oi = max(i for i, f in enumerate(stack) if len(f["args"]) >= 2)
                if oi + 1 < len(stack):
                    clo = stack[oi + 1]
                    st = [s for s, d in stmts if d == oi + 1]
                    st = st[-1] if st else None
                    if st and st["type"] == "AstStatAssign":
                        for v, e in zip(st["vars"], st["values"]):
                            if e is clo and local_name(v):
                                _, _, l2, c2 = loc(st)
                                seen[(l2, c2)] = (local_name(v), stack[oi]["args"][1]["name"])
            for v in n.values():
                walk(v, stack, stmts)
        elif isinstance(n, list):
            for v in n:
                walk(v, stack, stmts)
    walk(root, [], [])
    return [(l, c, var, pv) for (l, c), (var, pv) in seen.items()]


def decl_key(local):
    """Identity of a local: its declaration location."""
    return local["location"]


def outer_decls(root, target):
    """{declaration key: name} of every declaration that encloses `target` (a
    function node): the parameters and locals of the functions on the path
    from the root down to it. The innermost declaration of a name wins, so
    the VM closure's free names resolve to the keys the interpreter sees.
    A curried maker keeps the proto's data in the outermost function, which
    is not the maker the lifter calls, so its names are only reachable here."""
    found = {}

    def visit(n, stack):
        if isinstance(n, dict):
            pushed = n.get("type") == "AstExprFunction"
            if pushed:
                stack.append(n)
            if n is target:
                for fn in stack[:-1]:
                    found.update(_decls_in(fn))
            for v in n.values():
                visit(v, stack)
            if pushed:
                stack.pop()
        elif isinstance(n, list):
            for v in n:
                visit(v, stack)

    visit(root, [])
    return found


def _free_names(fn):
    """Names used inside `fn` whose declaration is outside it (its free
    upvalues). The capture hook runs inside the enclosing function, where
    those names are still in scope."""
    own = set(_decls_in(fn))
    names = set()

    def visit(n):
        if isinstance(n, dict):
            if n.get("type") == "AstExprLocal" and decl_key(n["local"]) not in own:
                names.add(n["local"]["name"])
            for v in n.values():
                visit(v)
        elif isinstance(n, list):
            for v in n:
                visit(v)
    visit(fn["body"])
    return sorted(names)


def _dispatch_local_info(out, stack):
    """The maker shape with nothing to hook onto: the VM closure is returned
    (a curried maker, or one that decodes the proto inside the dispatcher's
    own closure), so no statement stores it. Hook in front of the
    dispatcher's own body instead, where the proto state is already in the
    closure's first locals and the VM state is reachable as free upvalues.
    True when an entry was registered."""
    if not stack:
        return False
    vm_idx = _vm_stack_idx(stack)
    clo = stack[vm_idx]
    if not clo.get("vararg") or clo.get("args"):
        return False
    body = clo.get("body")
    bbody = body.get("body") if isinstance(body, dict) else None
    if not bbody or len(bbody) < 2 or bbody[0].get("type") != "AstStatLocal" \
            or not bbody[0].get("vars"):
        return False
    # the proto is what the first local holds, or the first local filled by a
    # call (the builds that decode it in the closure: `local P=A[113](x)`)
    target_idx, pv = 0, bbody[0]["vars"][0]["name"]
    for si in range(len(bbody) - 1):
        st = bbody[si]
        if st.get("type") != "AstStatLocal":
            break
        vars_ = st.get("vars") or []
        hit = next(((vi, val) for vi, val in enumerate(st.get("values") or [])
                    if isinstance(val, dict) and _unwrap(val).get("type") == "AstExprCall"
                    and vi < len(vars_)), None)
        if hit:
            target_idx, pv = si, vars_[hit[0]]["name"]
            break
    first, second = bbody[target_idx], bbody[target_idx + 1]
    l2, c2, _, _ = loc(second)
    key = ("disp", l2, c2)
    if key in out:
        return True
    shadowed = {v["name"] for si in range(target_idx + 1) for v in (bbody[si].get("vars") or [])}
    out[key] = {"at": (l2, c2), "var": pv, "proto": pv, "mode": "dispatch_local",
                "pf_key": '"disp@%d,%d"' % (l2, c2),
                "maker": stack[vm_idx - 1] if vm_idx >= 1 else None,
                "vm": clo, "stmt": first,
                "captures": [nm for nm in _free_names(clo) if nm not in shadowed],
                "curried3": _curried3_of(stack, vm_idx),
                "chain": stack[:max(vm_idx - 1, 0)]}
    return True


def maker_info(root, disp=None):
    """closure_makers() plus what the runtime capture needs: for each maker,
    {"at": (line, col), "var": closure local, "proto": proto param name,
     "maker": maker AstExprFunction, "vm": the VM closure AstExprFunction,
     "captures": [maker-level local names the VM closure uses],
     "chain": the functions enclosing the maker}.
    Only names that are not shadowed at the insertion point are returned.
    A maker that stores its closure nowhere (v15.1's curried makers) is
    described by _dispatch_local_info instead, with "mode" set."""
    disp_nodes = {id(d["node"]) for d in (disp if disp is not None else find_dispatchers(root))}
    out = {}

    def walk(n, stack, stmts):
        if isinstance(n, dict):
            t = n.get("type")
            if t == "AstExprFunction":
                stack = stack + [n]
            if t and t.startswith("AstStat"):
                stmts = stmts + [(n, len(stack))]
            if id(n) in disp_nodes and _loop_body(n) is not None:
                registered = False
                oi = max((i for i, f in enumerate(stack) if len(f["args"]) >= 2), default=-1)
                if oi != -1 and oi + 1 < len(stack):
                    clo = stack[oi + 1]
                    st = [s for s, d in stmts if d == oi + 1]
                    st = st[-1] if st else None
                    if st and st["type"] == "AstStatAssign":
                        for v, e in zip(st["vars"], st["values"]):
                            if _unwrap(e) is clo and local_name(v):
                                _, _, l2, c2 = loc(st)
                                registered = True
                                if (l2, c2) in out:
                                    break
                                pi, ui = _maker_params(stack[oi])
                                out[(l2, c2)] = {"at": (l2, c2), "var": local_name(v),
                                                 "proto": stack[oi]["args"][pi]["name"],
                                                 "proto_index": pi, "upvals_index": ui,
                                                 # key the entry hooks number protos by (__PID);
                                                 # closure -> proto attribution must use the same
                                                 "pf_key": stack[oi]["args"][pi]["name"],
                                                 "maker": stack[oi], "vm": clo, "stmt": st,
                                                 "chain": stack[:oi]}
                                break
                if not registered:
                    _dispatch_local_info(out, stack)
            for v in n.values():
                walk(v, stack, stmts)
        elif isinstance(n, list):
            for v in n:
                walk(v, stack, stmts)
    walk(root, [], [])
    for info in out.values():
        if "captures" not in info:
            info["captures"] = _captures(info)
    return list(out.values())


def _maker_params(maker):
    """(proto parameter index, upvalue-list parameter index) of a closure maker.
    Layouts differ: function(e, proto, upvals) or, with repeated names,
    function(g, d, d, d, d, j) where the proto is the last one. The proto is
    the parameter indexed through itself (P[P[k]]: its fields are keyed by
    its own entries); the upvalue list is the first other parameter the body
    uses (only the last of repeated names is visible)."""
    args = maker["args"]
    visible = {}
    for i, a in enumerate(args):
        visible[a["name"]] = i
    counts = {}
    kcounts = {}    # P[<number>]: the proto of makers that index it directly
    used = set()

    def visit(n):
        if isinstance(n, dict):
            if n.get("type") == "AstExprLocal":
                used.add(n["local"]["location"])
            if n.get("type") == "AstExprIndexExpr" and n["expr"].get("type") == "AstExprLocal" \
                    and n["index"].get("type") == "AstExprIndexExpr" \
                    and n["index"]["expr"].get("type") == "AstExprLocal" \
                    and n["index"]["expr"]["local"]["location"] == n["expr"]["local"]["location"]:
                k = n["expr"]["local"]["location"]
                counts[k] = counts.get(k, 0) + 1
            if n.get("type") == "AstExprIndexExpr" and n["expr"].get("type") == "AstExprLocal" \
                    and n["index"].get("type") == "AstExprConstantNumber":
                k = n["expr"]["local"]["location"]
                kcounts[k] = kcounts.get(k, 0) + 1
            for v in n.values():
                visit(v)
        elif isinstance(n, list):
            for v in n:
                visit(v)
    visit(maker["body"])
    cands = [i for i in visible.values() if i > 0]
    pi = max(cands, key=lambda i: (counts.get(args[i]["location"], 0), i == 1)) if cands else 1
    if not counts.get(args[pi]["location"]):
        pi = 1
        # function(v, R, R, R, g, g) with `B = R[11]`: the visible R
        kc = [i for i in cands if kcounts.get(args[i]["location"])]
        if kc:
            pi = max(kc, key=lambda i: kcounts[args[i]["location"]])
    others = sorted(i for i in visible.values() if i not in (0, pi) and args[i]["location"] in used)
    ui = others[0] if others else pi + 1
    return pi, ui


def _decls_in(fn):
    """Declaration keys of locals declared directly in fn (params and body,
    not inside nested functions)."""
    keys = {}

    def visit(n):
        if isinstance(n, dict):
            t = n.get("type")
            if t == "AstExprFunction" and n is not fn:
                return
            if t == "AstStatLocal":
                for v in n["vars"]:
                    keys[decl_key(v)] = v["name"]
            elif t == "AstStatLocalFunction":
                keys[decl_key(n["name"])] = n["name"]["name"]
            elif t in ("AstStatFor",):
                keys[decl_key(n["var"])] = n["var"]["name"]
            elif t == "AstStatForIn":
                for v in n["vars"]:
                    keys[decl_key(v)] = v["name"]
            for v in n.values():
                visit(v)
        elif isinstance(n, list):
            for v in n:
                visit(v)
    for a in fn["args"]:
        keys[decl_key(a)] = a["name"]
    visit(fn["body"])
    return keys


def _captures(info):
    maker_decls = _decls_in(info["maker"])
    used = {}

    def visit(n):
        if isinstance(n, dict):
            if n.get("type") == "AstExprLocal":
                k = decl_key(n["local"])
                if k in maker_decls:
                    used[k] = maker_decls[k]
            for v in n.values():
                visit(v)
        elif isinstance(n, list):
            for v in n:
                visit(v)
    visit(info["vm"])
    names = {}
    for k, name in used.items():
        names.setdefault(name, []).append(k)
    # a name declared twice at maker level would be ambiguous at the insertion point
    dup = {nm for nm, ks in names.items() if len(ks) > 1}
    by_name = {}
    for k, nm in maker_decls.items():
        by_name.setdefault(nm, []).append(k)
    return sorted(nm for nm in names if nm not in dup and len(by_name[nm]) == 1)
