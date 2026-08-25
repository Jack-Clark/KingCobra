package verifier;

import java.io.BufferedInputStream;
import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.google.common.graph.Graphs;

import algo.DFSCycleDetection;
import graph.EdgeType;
import graph.OpNode;
import graph.PrecedenceGraph;
import graph.TxnNode;
import util.ChengLogger;
import util.LogReceiver;
import util.Profiler;
import util.RemoteLogBuffer;
import util.VeriConstants;
import util.VeriConstants.LoggerType;


public abstract class AbstractLogVerifier extends AbstractVerifier {
	
	protected File log_dir = null;
	protected Map<String, DataInputStream> alive_streams = null;
	
	public AbstractLogVerifier(String logfd) {
		super();
		if (logfd == null) {
			remote_log = true;
		} else {
			log_dir = new File(logfd);
		}
		alive_streams = new HashMap<String,DataInputStream>();
	}
	
	//	 =======Log Finder===========
	
	public static ArrayList<File> findLogWithSuffix(File folder, String suffix) {
		assert folder.isDirectory();
		ArrayList<File> logs = new ArrayList<File>();
		for (File f : folder.listFiles()) {
			if (f.isFile() && f.getName().endsWith(suffix)) {
				logs.add(f);
			}
		}
		return logs;
	}

	public static ArrayList<File> findOpLogInDir(File folder) {
		return findLogWithSuffix(folder, ".log");
	}
	
	public static ArrayList<File> findWOLogInDir(File folder) {
		return findLogWithSuffix(folder, ".wlog");
	}
	
	// =======Local Log Parsing===========
	
	DataInputStream GetStreamFromLog(File log, String client_name) throws IOException {
		if (!alive_streams.containsKey(client_name)) {
			// Either (1) read to memory
			// byte[] fbytes = LoadingLogFromFile(log);
			// DataInputStream in = new DataInputStream(new ByteArrayInputStream(fbytes));

			// OR (2) use builtin lib
			BufferedInputStream bf = new BufferedInputStream(new FileInputStream(log), 1024 * 1024);
			DataInputStream in = new DataInputStream(bf);
			assert in.markSupported();
			
			alive_streams.put(client_name, in);
			
			return in;
		}
			
		return alive_streams.get(client_name);
	}
	
	DataInputStream GetStreamFromRemote(RemoteLogBuffer rlb, String client_name) throws IOException {
		if (!alive_streams.containsKey(client_name)) {
			DataInputStream in = rlb.getClientStream(client_name);
			//assert in.markSupported();
			alive_streams.put(client_name, in);
			return in;
		}
			
		return alive_streams.get(client_name);
	}
	
	// === load logs and construct a graph
	
	public boolean loadLogs(ArrayList<File> opfiles, PrecedenceGraph out_pg) {
		// 1. construct a graph with TO, WR order and *partial WW order*
		// 1.1 load log from files
		try {
			for (File f : opfiles) {
				// add CO edges and some WW edges (from read-modify-write)
				String client_name = f.getName();
				DataInputStream in = GetStreamFromLog(f, client_name);
				ExtractClientLogFromStream(in, out_pg, client_name);
			}
		} catch (IOException e) {
			e.printStackTrace();
		}
		
		// 1.2 add edges
		boolean ret = updateEdges(out_pg, true);
		return ret;
	}
	
	public boolean loadRemoteLogs(PrecedenceGraph out_pg) {
		RemoteLogBuffer rlb = RemoteLogBuffer.getInstance();
		
		Profiler prof = Profiler.getInstance();
		prof.startTick("loadfile1");
		// 1. wait for all clients [the first time]
		// make sure the verifier sees all clients
		if (!rlb.ifInit()) {
			rlb.waitClientConnect();
		}
		assert rlb.getClients().size() == VeriConstants.TOTAL_CLIENTS;
		assert LogReceiver.getInstance().getClients().size() == VeriConstants.TOTAL_CLIENTS;

		// 2. construct graph with CO, WR, RW
		while(this.new_txns_this_turn.size() < VeriConstants.MIN_PROCESSING_NEW_TXN) {
			try {
				for (String client_name : rlb.getClients()) {
					DataInputStream in = GetStreamFromRemote(rlb, client_name);
					ExtractClientLogFromStream(in, out_pg, client_name);
				}
			} catch (IOException e) {
				e.printStackTrace();
				assert false; // FIXME: stop entirely for now
			}
			ChengLogger.println("fetched txns in this round: " + this.new_txns_this_turn.size() + "/" + VeriConstants.MIN_PROCESSING_NEW_TXN);
			if (this.new_txns_this_turn.size() < VeriConstants.MIN_PROCESSING_NEW_TXN) {
				prof.endTick("loadfile1");
				try {
					Thread.sleep(500); // wait for logs
				} catch (InterruptedException e) {
					e.printStackTrace();
				}
				prof.startTick("loadfile1");
			}
		}
		ChengLogger.print(rlb.status());
		prof.endTick("loadfile1");
		
		prof.startTick("loadfile2");
		// 3. add edges
		boolean ret = updateEdges(out_pg, false);
		prof.endTick("loadfile2");
		
		return ret;
	}


	/** Parsed once and reused; in rounds mode this method runs per round. */
	private VersionOrder version_order = null;

	private VersionOrder versionOrder() {
		if (version_order == null) {
			version_order = VersionOrder.load(VeriConstants.VERSION_ORDER_PATH);
			ChengLogger.println(LoggerType.INFO,
					"Version order loaded: " + version_order.keyCount() + " keys from "
							+ VeriConstants.VERSION_ORDER_PATH);
		}
		return version_order;
	}

	/**
	 * Resolves the transaction that wrote a given version of a key, or null if
	 * this verifier has not seen it.
	 *
	 * A version can be absent legitimately: in rounds mode the writer may already
	 * have been garbage collected, and a version order supplied by a database may
	 * name versions outside the log being checked. Callers skip the edge rather
	 * than failing, which is the same weakening a partial version order produces.
	 */
	private Long writerOf(long key, long version) {
		Map<Long, Long> versions = kvToWid.get(key);
		if (versions == null) {
			return null;
		}
		Long wid = versions.get(version);
		if (wid == null) {
			return null;
		}
		return wid2txnid.get(wid);
	}

	/**
	 * Adds VO edges to the graph. A version order tells us, for each key, which
	 * write produced which version; every pair of writes to the same key therefore
	 * has a known direction, and an edge in that direction replaces a WW constraint
	 * the solver would otherwise have to search over.
	 *
	 * With ALL_VO_EDGES the transitive closure is materialised (an edge from every
	 * earlier version's writer). Otherwise only the direct predecessor gets an edge,
	 * which is the same reachability relation with far fewer edges.
	 */
	private void addVersionOrderEdges(PrecedenceGraph graph, Set<TxnNode> new_txns) {
		long start = System.nanoTime();
		VersionOrder order = versionOrder();
		long edges = 0;
		long skipped = 0;

		for (TxnNode tx : new_txns) {
			for (OpNode op : tx.getOps()) {
				if (op.isRead) {
					continue;
				}
				long key = op.key_hash;
				int position = order.positionOf(key, op.val_hash);
				if (position < 0) {
					continue; // this order does not mention the version we wrote
				}

				// Every earlier version precedes this write. ALL_VO_EDGES draws all
				// of them; otherwise the direct predecessor alone carries the same
				// reachability.
				List<Long> versions = order.versionsOf(key);
				int first = VeriConstants.ALL_VO_EDGES ? 0 : position - 1;
				for (int i = Math.max(first, 0); i < position; i++) {
					Long from = writerOf(key, versions.get(i));
					if (from == null) {
						skipped++;
						continue;
					}
					graph.addEdge(from, tx.getTxnid(), EdgeType.VO);
					edges++;
				}
			}
		}

		long duration = System.nanoTime() - start;
		ChengLogger.println(LoggerType.INFO,
				"VO edges added = " + edges + " in " + (duration / 1000000) + "ms");
		if (skipped > 0) {
			// Expected in rounds mode after collection; in one-shot mode it means the
			// version order names writes that are not in the log.
			ChengLogger.println(LoggerType.WARNING,
					"VO edges skipped = " + skipped + " (writer not present in this verifier)");
		}
	}

	private boolean updateEdges(PrecedenceGraph out_pg, boolean check_cyclic) {
		// add WR edges
		AddWREdges(out_pg, this.new_txns_this_turn, this);
		// add TO edges
		if (VeriConstants.TIME_ORDER_ON) {
			//AddConflictSEREdges(out_pg);
			AddTimeOrderEdges(out_pg);
		}
		// add RW edges
		UpdateWid2Txnid(out_pg, this.new_txns_this_turn);
		AddRWEdges(out_pg, this.new_txns_this_turn, this.wid2txnid, this);

		if (VeriConstants.VERSION_ORDER_ON) {
			addVersionOrderEdges(out_pg, this.new_txns_this_turn);
		}

		if (!check_cyclic) {
			return true;
		}
		
		// boolean hasCycle = DFSCycleDetection.CycleDetection(out_pg.getGraph());
		boolean hasCycle = DFSCycleDetection.hasCycleHybrid(out_pg.getGraph());
		if (hasCycle) {
			DFSCycleDetection.PrintOneCycle(out_pg);
			return false;
		} else {
			return true;
		}
	}

}
