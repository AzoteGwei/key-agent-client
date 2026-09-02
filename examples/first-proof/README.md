# first-proof

Three contracts whose answers are already known, and a walk-through of what to do with the one
that is only missing a specification.

Nothing here is a library or a fixture to import. It exists because a proof that does not close is
ambiguous until you have watched one close: a wrong jar, too small a heap, a missing class path
and a contract that simply does not hold all look the same from outside.

| Class | Proving it gives | Because |
| --- | --- | --- |
| `Max` | `closed true`, exit `0` | it is correct and provable |
| `BrokenMax` | `closed false`, exit `1` | the code is wrong |
| `Summer` | `closed false`, exit `1` | a `loop_invariant` has not been written |

`Max` and `BrokenMax` carry byte-for-byte the same specification and differ only in the body.
Anything that reports the same verdict for both is broken, whichever verdict it reports.

## Check the setup

```sh
java -Xmx4g -jar keyext.server-*-exe.jar --port 0 --workspace examples/first-proof &

key-agent load .
# env	env-e84opq9w                                    yours will differ; use it below
key-agent prove env-e84opq9w 'Max[Max::max(int,int)].JML normal_behavior operation contract.0'
# closed	true
```

If that is not `closed true`, stop: the problem is the jar, the heap or the server, and nothing
you do to a specification will help. The [usage guide][guide] walks all three contracts.

---

## Tutorial: from `NEEDS_SPEC` to `closed`

`Summer.sumTo` is correct and does not prove. This is the most common shape of a real failure, and
the loop out of it is five steps: ask what is missing, write it, read what the prover says next,
check that answer against the running code, and decide what to do about it. Every command below is
`key-agent`; the same sequence over MCP is `key_load`, `key_prove`, `key_inspect`, `key_script`.

Work on a copy. This directory is the setup check, and it is only that for as long as `Summer`
still fails the way it is documented to.

```sh
mkdir -p /tmp/summer && cp Summer.java /tmp/summer/
```

### First, pin what you are proving under

KeY's proof settings live in the user's home directory, not in the project, and they change the
answer. Two of them decide this walk-through. `intRules` says whether `int` arithmetic wraps the
way Java's does or is treated as unbounded; `NON_LIN_ARITH_OPTIONS_KEY` says whether the prover
will reason about multiplication at all. A machine with no settings file gets KeY's own defaults —
overflow ignored, non-linear arithmetic off — and under those the same source proves differently
from what is printed below.

That is worth more than a footnote. **A contract proved with overflow ignored is a weaker result
than the same contract proved under `javaSemantics`, and `closed: true` does not say which one you
got.** If a project cares, it says so, and the place it says so is its `.key` file — which is what
KeY's own examples do. Save this beside the copy as `/tmp/summer/project.key`:

```key
\settings {
"
[Choice]DefaultChoices=intRules-intRules\\:javaSemantics
[StrategyProperty]NON_LIN_ARITH_OPTIONS_KEY=NON_LIN_ARITH_DEF_OPS
"
}

\javaSource ".";

\chooseContract "Summer[Summer::sumTo(int)].JML normal_behavior operation contract.0";
```

**Load the `.key` file from here on, not the directory.** A directory load ignores any `.key` file
sitting in it and runs under whatever the machine has, which is the whole failure this is here to
prevent. Loading the `.key` still lists every contract under its `\javaSource`, so nothing is lost
by it.

Two things it does that are worth knowing. `\chooseContract` makes KeY create that proof at load
time, so `obligations` reports the contract as `proved` before you have run anything — read
`closed` from `prove`, not from that column. And KeY writes the settings it took from the file
back into `~/.key`, so they become the machine's defaults afterwards; on your own machine that is
a real change, not just a change for this run.

The setup check above stays on a directory load on purpose: those three answers are the same
under any settings, which is what makes them worth checking a setup with.

### 1. Ask what is missing

```sh
key-agent load /tmp/summer/project.key
# env	env-bayk1n0c
key-agent prove env-bayk1n0c 'Summer[Summer::sumTo(int)].JML normal_behavior operation contract.0'
# outcome	EXHAUSTED
# closed	false
# openGoals	1
key-agent explain prf-30ww9bfm
# 28	NEEDS_SPEC	LoopScopeInvariantRule	file:///tmp/summer/Summer.java:25
# 28	NEEDS_SPEC	WhileInvariantRule	file:///tmp/summer/Summer.java:25
```

Paths are resolved by the server against the workspace it was started with, so a directory outside
it needs an absolute path.

`NEEDS_SPEC` is the actionable diagnosis: a rule wanted to apply and could not, because something
a person has to write is not there. It hands over a file and a line. Open that line — it is the
`while` — and the missing thing is a loop invariant.

The other diagnosis, `no-rule-applies`, means the opposite: nothing is waiting on a specification,
so writing more JML will change nothing. `BrokenMax` gives that one.

### 2. Write the invariant

An invariant has to say three things: where `i` has got to, what is true of the result so far, and
that the loop is getting somewhere.

```java
/*@ loop_invariant 1 <= i && i <= n + 1;
  @ loop_invariant total >= 0;
  @ assignable \nothing;
  @ decreases n - i + 1;
  @*/
while (i <= n) {
```

Then prove it again. **A new `load` is needed:** the server holds the sources it parsed, and
editing a file underneath it changes nothing until it is loaded again.

```sh
key-agent load /tmp/summer/project.key
# env	env-7pm2ktx4                                    a new one; the old env is the old text
key-agent prove env-7pm2ktx4 'Summer[Summer::sumTo(int)].JML normal_behavior operation contract.0'
# closed	false
# openGoals	2
```

Still open — and now with *more* goals than before. That is progress, not a regression: the
invariant let symbolic execution through the loop, and what is on the other side is a question
that was never reached before.

### 3. Read what it is now stuck on

```sh
key-agent explain prf-3qub569s
# 1070	no-rule-applies	nothing is waiting on a specification; the goal is likely not provable
# 1275	no-rule-applies	nothing is waiting on a specification; the goal is likely not provable
```

The diagnosis has changed. Nothing is waiting on a specification any more, so this is no longer a
"write more JML" problem — the guide's [step 5][step5] is this fork in the road. When `explain`
has nothing to point at, read the goal itself:

```sh
key-agent sequent prf-3qub569s 1275 --format STRUCTURED
# A.claim	total_0 <= 4294967295 + i_0 * -1
# A.claim	(2147483648 + i_0 + total_0) / 4294967296 = 1
# A.claim	total_0 >= 2147483648 + i_0 * -1
# ...
# A.claim	total_0 <= 2147483647
```

Read the third line as `total + i >= 2147483648`, and `2147483648` as `Integer.MAX_VALUE + 1`.
The division by `4294967296` above it is the wrap itself: 2^32, arithmetic modulo the width of an
`int`. The prover has reached a state where the next `total += i` leaves the range of the type.
This is not a proof problem. It is an overflow in the method — and it is visible only because the
`.key` file asked for `javaSemantics`.

### 4. Confirm it outside the prover

A prover that says something is unprovable is worth checking against the thing itself, especially
before changing a contract on its word.

```sh
cd /tmp/summer
printf '/open Summer.java\nSystem.out.println(Summer.sumTo(65536));\n/exit\n' | jshell -q -
# -2147450880
```

`jshell` is the `jdk.jshell` module of a JDK: a JRE does not have it, and a jlink-trimmed image
may have dropped it. Where it is missing, `javac` does the same job. Do it on a second copy —
`javac` leaves `.class` files behind, and the next step points the prover at this directory.

```sh
mkdir /tmp/summer-run && cp Summer.java /tmp/summer-run/ && cd /tmp/summer-run
cat > Check.java <<'EOF'
public class Check {
    public static void main(String[] args) {
        System.out.println(Summer.sumTo(65536));
    }
}
EOF
javac Summer.java Check.java && java Check
# -2147450880
```

`java Check.java` on its own will not do: single-file source mode compiles the one file and does
not go looking for `Summer`.

`sumTo(65536)` really does return a negative number, so `ensures \result >= 0` really is false.
`sumTo(65535)` is `2147450880`, which fits. The contract holds up to 65535 and not one past it,
and that number is now a fact about the method rather than a guess about the prover.

### 5. Decide, then close it

There are two honest moves, and choosing between them is the user's, not the prover's:

- **Narrow the precondition**, if the method is only ever meant for small `n`.
- **Change the code**, if it is meant to take any `int` — `long` accumulation, or a documented
  saturating result.

What is *not* available is weakening `ensures \result >= 0` until the proof closes. A contract
narrowed until it is provable can be worse than no contract, because it still reads as a
guarantee. Say what you found and let the user pick.

Taking the first, with an exact invariant so the bound is the method's real one rather than an
artefact of a weak specification:

```java
public final class Summer {

    private Summer() {
    }

    /*@ public normal_behavior
      @   requires 0 <= n && n <= 65535;
      @   ensures \result >= 0;
      @   assignable \nothing;
      @*/
    public static int sumTo(int n) {
        int total = 0;
        int i = 1;
        /*@ loop_invariant 1 <= i && i <= n + 1;
          @ loop_invariant (\bigint) total == ((\bigint) i - 1) * (\bigint) i / 2;
          @ assignable \nothing;
          @ decreases n - i + 1;
          @*/
        while (i <= n) {
            total += i;
            i++;
        }
        return total;
    }
}
```

```sh
key-agent load /tmp/summer/project.key
key-agent prove env-q4v8rz1c 'Summer[Summer::sumTo(int)].JML normal_behavior operation contract.0'
# proof	prf-1gdalf5f
# outcome	EXHAUSTED
# closed	true
# openGoals	0
```

Exit status `0`.

Two things in that invariant are worth keeping. `(\bigint)` is JML's unbounded integer: the
invariant now states the exact sum, and states it in arithmetic that cannot itself overflow, which
a specification written in `int` would have done at `n = 65535`. And the bound in `requires` came
out of the method rather than out of the proof — `65535` is where `sumTo` stops holding its
promise, not where the prover stopped coping.

A weaker invariant closes too, but at a price: `total <= (i - 1) * n` needs `n <= 46340` to keep
its own arithmetic in range, so the contract ends up narrower than the method is. When a
precondition looks arbitrary, suspect the invariant before believing the bound.

### When the specification is right and it still will not close

`explain` says `no-rule-applies`, the search says `EXHAUSTED`, and you have satisfied yourself the
claim is true. That is what proof scripts are for — `key-agent script`, or `key_script` over MCP,
with `smt;` to hand a goal to a solver. The guide's [step 7][step7] covers it.

### Save what closed

```sh
key-agent save prf-1gdalf5f --bundle
```

A closed proof nobody kept is a result nobody can check.

[guide]: ../../docs/guide.md
[step5]: ../../docs/guide.md#5-when-it-did-not-close-find-out-which-of-three-things-happened
[step7]: ../../docs/guide.md#7-when-the-prover-has-given-up-do-what-a-person-would
