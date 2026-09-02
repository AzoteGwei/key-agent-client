/**
 * The one that closes.
 *
 * <p>Prove this contract first. It is the whole point of this directory: until you have seen
 * {@code closed true} come back once, nothing else the prover says about your own code can be
 * interpreted, because a failure to prove and a broken setup look identical from outside.
 *
 * <p>Its specification is byte-for-byte the one in {@link BrokenMax}. Only the body differs.
 */
public final class Max {

    private Max() {
    }

    /*@ public normal_behavior
      @   ensures \result >= a && \result >= b;
      @   ensures \result == a || \result == b;
      @   assignable \nothing;
      @*/
    public static int max(int a, int b) {
        return a >= b ? a : b;
    }
}
