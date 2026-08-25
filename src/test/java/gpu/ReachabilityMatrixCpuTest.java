package gpu;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

import com.google.common.graph.GraphBuilder;
import com.google.common.graph.MutableGraph;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import graph.TxnNode;
import util.VeriConstants;

/**
 * Exercises the reachability matrix with GPU_MATRIX off, which is how King
 * Cobra runs on a machine without CUDA. Nothing here touches a native library.
 *
 * Correctness is checked against a brute-force transitive closure computed
 * independently in the test, rather than against the GPU implementation, so
 * these tests are meaningful without a GPU present.
 */
public class ReachabilityMatrixCpuTest {

	private boolean saved_gpu_matrix;

	@BeforeEach
	public void useCpuPath() {
		saved_gpu_matrix = VeriConstants.GPU_MATRIX;
		VeriConstants.GPU_MATRIX = false;
	}

	/** Restores the global so test order cannot leak state. */
	@org.junit.jupiter.api.AfterEach
	public void restore() {
		VeriConstants.GPU_MATRIX = saved_gpu_matrix;
	}

	/** Builds a DAG over ids 0..n-1, with edges only from lower to higher ids. */
	private static MutableGraph<TxnNode> dag(int n, int[][] edges, List<TxnNode> out) {
		MutableGraph<TxnNode> g = GraphBuilder.directed().allowsSelfLoops(true).build();
		for (int i = 0; i < n; i++) {
			TxnNode t = new TxnNode(i);
			g.addNode(t);
			out.add(t);
		}
		for (int[] e : edges) {
			g.putEdge(out.get(e[0]), out.get(e[1]));
		}
		return g;
	}

	/** Floyd-Warshall over the same edges, written independently of the code under test. */
	private static boolean[][] closure(int n, int[][] edges) {
		boolean[][] r = new boolean[n][n];
		for (int[] e : edges) {
			r[e[0]][e[1]] = true;
		}
		for (int k = 0; k < n; k++) {
			for (int i = 0; i < n; i++) {
				for (int j = 0; j < n; j++) {
					if (r[i][k] && r[k][j]) {
						r[i][j] = true;
					}
				}
			}
		}
		return r;
	}

	private static void assertMatches(ReachabilityMatrix rm, List<TxnNode> txns, boolean[][] expected) {
		int n = expected.length;
		for (int i = 0; i < n; i++) {
			for (int j = 0; j < n; j++) {
				int si = rm.txnid2index(txns.get(i).getTxnid());
				int di = rm.txnid2index(txns.get(j).getTxnid());
				assertEquals(expected[i][j], rm.reach(si, di),
						"reach(" + i + ", " + j + ")");
			}
		}
	}

	@Test
	public void computesTransitiveClosureOfAChain() {
		int[][] edges = {{0, 1}, {1, 2}, {2, 3}};
		List<TxnNode> txns = new ArrayList<TxnNode>();
		MutableGraph<TxnNode> g = dag(4, edges, txns);

		ReachabilityMatrix rm = ReachabilityMatrix.getReachabilityMatrix(g, null);

		assertMatches(rm, txns, closure(4, edges));
		assertTrue(rm.reach(rm.txnid2index(0), rm.txnid2index(3)), "0 should reach 3 transitively");
		assertFalse(rm.reach(rm.txnid2index(3), rm.txnid2index(0)), "3 must not reach 0");
	}

	@Test
	public void computesTransitiveClosureOfADiamond() {
		int[][] edges = {{0, 1}, {0, 2}, {1, 3}, {2, 3}};
		List<TxnNode> txns = new ArrayList<TxnNode>();
		MutableGraph<TxnNode> g = dag(4, edges, txns);

		ReachabilityMatrix rm = ReachabilityMatrix.getReachabilityMatrix(g, null);

		assertMatches(rm, txns, closure(4, edges));
		assertFalse(rm.reach(rm.txnid2index(1), rm.txnid2index(2)), "siblings must not reach each other");
	}

	@Test
	public void unconnectedNodesReachNothing() {
		int[][] edges = {};
		List<TxnNode> txns = new ArrayList<TxnNode>();
		MutableGraph<TxnNode> g = dag(3, edges, txns);

		ReachabilityMatrix rm = ReachabilityMatrix.getReachabilityMatrix(g, null);

		assertMatches(rm, txns, closure(3, edges));
	}

	/**
	 * connect() previously asserted GPU_MATRIX and called into the GPU library
	 * unconditionally, so adding edges was impossible without CUDA. This is the
	 * regression test for that path.
	 */
	@Test
	public void connectAddsEdgesAndRecomputesClosureOnCpu() {
		int[][] edges = {{0, 1}, {2, 3}};
		List<TxnNode> txns = new ArrayList<TxnNode>();
		MutableGraph<TxnNode> g = dag(4, edges, txns);
		ReachabilityMatrix rm = ReachabilityMatrix.getReachabilityMatrix(g, null);

		assertFalse(rm.reach(rm.txnid2index(0), rm.txnid2index(3)), "not yet connected");

		// Joining the two chains should make 0 reach 3.
		rm.connect(new Long[]{1L}, new Long[]{2L});

		int[][] after = {{0, 1}, {2, 3}, {1, 2}};
		assertMatches(rm, txns, closure(4, after));
		assertTrue(rm.reach(rm.txnid2index(0), rm.txnid2index(3)), "0 should now reach 3");
	}

	@Test
	public void connectHandlesSeveralEdgesAtOnce() {
		int[][] edges = {{0, 1}, {2, 3}, {4, 5}};
		List<TxnNode> txns = new ArrayList<TxnNode>();
		MutableGraph<TxnNode> g = dag(6, edges, txns);
		ReachabilityMatrix rm = ReachabilityMatrix.getReachabilityMatrix(g, null);

		rm.connect(new Long[]{1L, 3L}, new Long[]{2L, 4L});

		int[][] after = {{0, 1}, {2, 3}, {4, 5}, {1, 2}, {3, 4}};
		assertMatches(rm, txns, closure(6, after));
		assertTrue(rm.reach(rm.txnid2index(0), rm.txnid2index(5)), "the whole chain should be connected");
	}

	/**
	 * The property that matters: for randomly generated DAGs, the CPU matrix
	 * agrees with an independent closure, before and after connect().
	 */
	@Test
	public void agreesWithBruteForceOnRandomDags() {
		Random r = new Random(20210823); // fixed seed: failures reproduce
		for (int trial = 0; trial < 25; trial++) {
			int n = 5 + r.nextInt(8);
			List<int[]> edges = new ArrayList<int[]>();
			for (int i = 0; i < n; i++) {
				for (int j = i + 1; j < n; j++) {
					if (r.nextInt(100) < 25) {
						edges.add(new int[]{i, j});
					}
				}
			}
			int[][] edge_array = edges.toArray(new int[0][]);
			List<TxnNode> txns = new ArrayList<TxnNode>();
			MutableGraph<TxnNode> g = dag(n, edge_array, txns);

			ReachabilityMatrix rm = ReachabilityMatrix.getReachabilityMatrix(g, null);
			assertMatches(rm, txns, closure(n, edge_array));

			// connect() asserts the pair is not already reachable, so pick one that is not.
			boolean[][] c = closure(n, edge_array);
			for (int i = 0; i < n && true; i++) {
				int found = -1;
				for (int j = i + 1; j < n; j++) {
					if (!c[i][j]) {
						found = j;
						break;
					}
				}
				if (found >= 0) {
					rm.connect(new Long[]{(long) i}, new Long[]{(long) found});
					edges.add(new int[]{i, found});
					assertMatches(rm, txns, closure(n, edges.toArray(new int[0][])));
					break;
				}
			}
		}
	}
}
