package verifier;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * Covers the version order file format, which is the interop contract between
 * history_generator.py and the verifier. A silent change on either side would
 * otherwise go unnoticed until a run produced quietly wrong results.
 */
public class VersionOrderTest {

	/** Writes the format described in VersionOrder's javadoc. */
	private static byte[] encode(Map<Long, List<Long>> version_order) throws IOException {
		ByteArrayOutputStream bytes = new ByteArrayOutputStream();
		DataOutputStream out = new DataOutputStream(bytes);
		out.writeLong(version_order.size());
		for (Map.Entry<Long, List<Long>> e : version_order.entrySet()) {
			out.writeLong(e.getKey());
			out.writeLong(e.getValue().size());
			for (long v : e.getValue()) {
				out.writeLong(v);
			}
		}
		return bytes.toByteArray();
	}

	private static Map<Long, List<Long>> sample() {
		Map<Long, List<Long>> vo = new LinkedHashMap<Long, List<Long>>();
		vo.put(7L, Arrays.asList(0L, 1L, 2L, 3L));
		vo.put(8L, Arrays.asList(0L));
		vo.put(9L, Arrays.asList(0L, 5L, 11L)); // partial: versions may be skipped
		return vo;
	}

	private static VersionOrder decode(Map<Long, List<Long>> vo) throws IOException {
		return VersionOrder.read(new ByteArrayInputStream(encode(vo)));
	}

	@Test
	public void roundTripsThroughTheEncodedFormat() throws IOException {
		VersionOrder order = decode(sample());
		assertEquals(3, order.keyCount());
		assertEquals(Arrays.asList(0L, 1L, 2L, 3L), order.versionsOf(7L));
		assertEquals(Arrays.asList(0L), order.versionsOf(8L));
		assertEquals(Arrays.asList(0L, 5L, 11L), order.versionsOf(9L));
	}

	@Test
	public void preservesVersionOrderWithinAKey() throws IOException {
		Map<Long, List<Long>> vo = new LinkedHashMap<Long, List<Long>>();
		vo.put(1L, Arrays.asList(0L, 4L, 9L, 12L));
		// Order is the whole point: it is what gives each pair of writes a direction.
		assertEquals(Arrays.asList(0L, 4L, 9L, 12L), decode(vo).versionsOf(1L));
	}

	@Test
	public void indexesEachVersionByItsPosition() throws IOException {
		VersionOrder order = decode(sample());
		assertEquals(0, order.positionOf(7L, 0L));
		assertEquals(3, order.positionOf(7L, 3L));
		assertEquals(2, order.positionOf(9L, 11L), "positions follow the listed order, not the value");
	}

	@Test
	public void reportsUnknownKeysAndVersionsAsAbsent() throws IOException {
		VersionOrder order = decode(sample());
		assertEquals(-1, order.positionOf(1234L, 0L), "unknown key");
		assertEquals(-1, order.positionOf(7L, 99L), "unknown version");
		assertEquals(-1, order.positionOf(9L, 1L), "version omitted by a partial order");
		assertTrue(order.versionsOf(1234L).isEmpty());
	}

	@Test
	public void readsAnEmptyVersionOrder() throws IOException {
		VersionOrder order = decode(new LinkedHashMap<Long, List<Long>>());
		assertEquals(0, order.keyCount());
	}

	@Test
	public void readsAKeyWithNoVersions() throws IOException {
		Map<Long, List<Long>> vo = new LinkedHashMap<Long, List<Long>>();
		vo.put(3L, Arrays.<Long>asList());
		VersionOrder order = decode(vo);
		assertEquals(1, order.keyCount());
		assertTrue(order.versionsOf(3L).isEmpty());
		assertEquals(-1, order.positionOf(3L, 0L));
	}

	@Test
	public void loadsFromDisk(@TempDir Path dir) throws IOException {
		Path file = dir.resolve("version_order.vo");
		Files.write(file, encode(sample()));
		VersionOrder order = VersionOrder.load(file.toString());
		assertEquals(3, order.keyCount());
		assertEquals(Arrays.asList(0L, 1L, 2L, 3L), order.versionsOf(7L));
	}

	/**
	 * A missing file used to yield an empty order, so a run silently degraded to
	 * stock Cobra and a degraded result was indistinguishable from a good one.
	 * Loading is only attempted when VERSION_ORDER_ON is set, so this is a
	 * configuration error and is now raised as one.
	 */
	@Test
	public void missingFileIsAnError(@TempDir Path dir) {
		VersionOrder.LoadFailure failure = assertThrows(VersionOrder.LoadFailure.class,
				() -> VersionOrder.load(dir.resolve("absent.vo").toString()));
		assertTrue(failure.getMessage().contains("absent.vo"), failure.getMessage());
		assertTrue(failure.getMessage().contains("VERSION_ORDER_ON"),
				"the message should say how to proceed without a version order");
	}

	@Test
	public void truncatedFileIsAnError(@TempDir Path dir) throws IOException {
		Path file = dir.resolve("truncated.vo");
		byte[] full = encode(sample());
		Files.write(file, Arrays.copyOf(full, full.length / 2));
		assertThrows(VersionOrder.LoadFailure.class, () -> VersionOrder.load(file.toString()));
	}
}
