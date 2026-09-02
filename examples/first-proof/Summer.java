/**
 * The one that is under-specified.
 *
 * <p>{@code sumTo} is correct. What it lacks is a {@code loop_invariant}, so the prover has
 * nothing to reason about the loop with and stops. Wrong versus under-specified is the
 * distinction the diagnostics exist for: {@code key-agent explain} names a file and a line here,
 * and the answer is to go to that line and write the JML, not to give the search more time.
 *
 * <p>{@code n} is unbounded above on purpose, so unwinding the loop cannot finish the proof
 * either. There is no way through this method except an invariant.
 */
public final class Summer {

    private Summer() {
    }

    /*@ public normal_behavior
      @   requires 0 <= n;
      @   ensures \result >= 0;
      @   assignable \nothing;
      @*/
    public static int sumTo(int n) {
        int total = 0;
        int i = 1;
        while (i <= n) {
            total += i;
            i++;
        }
        return total;
    }
}
