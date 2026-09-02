/**
 * The one whose code is wrong.
 *
 * <p>It claims to return the larger of its two arguments and returns the first one, so
 * {@code max(1, 2) == 1} violates {@code ensures \result >= b}. The proof cannot close, and it is
 * the code that is at fault: the specification is byte-for-byte the one in {@link Max}, and that
 * one proves. Anything reporting the same verdict for both files is broken, whichever verdict it
 * reports.
 *
 * <p>{@code key-agent explain} says {@code no-rule-applies} here. Nothing is waiting on a
 * specification you could go and write; the prover simply ran out of moves, which is what an
 * unprovable claim looks like from the inside.
 */
public final class BrokenMax {

    private BrokenMax() {
    }

    /*@ public normal_behavior
      @   ensures \result >= a && \result >= b;
      @   ensures \result == a || \result == b;
      @   assignable \nothing;
      @*/
    public static int max(int a, int b) {
        return a;
    }
}
