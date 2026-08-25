package verifier;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * A version order: for each key, the sequence of values that key took, oldest
 * first. It is the extra information King Cobra consumes to turn unknown write
 * orderings into edges.
 *
 * On-disk layout, big-endian, every integer 8 bytes:
 *
 * <pre>
 *   &lt;number of keys&gt;
 *   per key:  &lt;key&gt; &lt;number of versions&gt; &lt;version&gt; ...
 * </pre>
 *
 * Keys or individual versions may be omitted; the order is treated as partial,
 * and omitted versions simply produce no edges.
 *
 * Alongside the ordered list this builds a value-to-position index, so locating
 * a version is a hash lookup rather than a scan of the key's version list.
 */
public class VersionOrder {

	private static final int READ_BUFFER_BYTES = 1024 * 1024;

	/** Raised when a version order was asked for but could not be loaded. */
	public static class LoadFailure extends RuntimeException {
		private static final long serialVersionUID = 1L;

		public LoadFailure(String message, Throwable cause) {
			super(message, cause);
		}
	}

	private final Map<Long, List<Long>> versions;
	private final Map<Long, Map<Long, Integer>> positions;

	private VersionOrder(Map<Long, List<Long>> versions) {
		this.versions = versions;
		this.positions = new HashMap<Long, Map<Long, Integer>>();
		for (Map.Entry<Long, List<Long>> e : versions.entrySet()) {
			List<Long> ordered = e.getValue();
			Map<Long, Integer> index = new HashMap<Long, Integer>(ordered.size() * 2);
			for (int i = 0; i < ordered.size(); i++) {
				index.put(ordered.get(i), i);
			}
			positions.put(e.getKey(), index);
		}
	}

	/**
	 * Reads a version order from a file.
	 *
	 * Loading is only attempted when VERSION_ORDER_ON is set, so a file that is
	 * missing or unreadable is a configuration error and is raised as one. It
	 * used to yield an empty order, which quietly turned the run into stock
	 * Cobra and made a degraded result indistinguishable from a good one.
	 */
	public static VersionOrder load(String filename) {
		InputStream stream = null;
		try {
			stream = new BufferedInputStream(new FileInputStream(filename), READ_BUFFER_BYTES);
			return read(stream);
		} catch (IOException e) {
			throw new LoadFailure("Could not read the version order file <" + filename + ">."
					+ " Set VERSION_ORDER_PATH to a file produced by history_generator.py,"
					+ " or set VERSION_ORDER_ON=false to verify without one.", e);
		} finally {
			closeQuietly(stream);
		}
	}

	/**
	 * Reads a version order from an already-open stream. Separated from
	 * {@link #load} so the format can be exercised without touching the disk.
	 */
	public static VersionOrder read(InputStream stream) throws IOException {
		Map<Long, List<Long>> versions = new HashMap<Long, List<Long>>();
		DataInputStream in = new DataInputStream(stream);
		long num_keys = in.readLong();

		for (long i = 0; i < num_keys; i++) {
			long key = in.readLong();
			long num_versions = in.readLong();
			List<Long> ordered = new ArrayList<Long>();
			for (long j = 0; j < num_versions; j++) {
				ordered.add(in.readLong());
			}
			assert !versions.containsKey(key);
			versions.put(key, ordered);
		}
		return new VersionOrder(versions);
	}

	private static void closeQuietly(InputStream stream) {
		if (stream == null) {
			return;
		}
		try {
			stream.close();
		} catch (IOException ignored) {
			// nothing useful to do while unwinding
		}
	}

	/** The versions recorded for a key, oldest first; empty if the key is unknown. */
	public List<Long> versionsOf(long key) {
		List<Long> ordered = versions.get(key);
		return ordered == null ? Collections.<Long>emptyList() : ordered;
	}

	/**
	 * Where a version sits in its key's order, or -1 if this order does not
	 * mention it. A partial order returns -1 for the versions it omits.
	 */
	public int positionOf(long key, long version) {
		Map<Long, Integer> index = positions.get(key);
		if (index == null) {
			return -1;
		}
		Integer position = index.get(version);
		return position == null ? -1 : position.intValue();
	}

	/** Number of keys this order mentions. */
	public int keyCount() {
		return versions.size();
	}
}
