package app.sonus.core

/** Port of versionTuple() from app/app_updater.py: the first four numbers of a text ("android-v0.2.1" -> 0, 2, 1). */
fun versionTuple(text: String?): List<Int> {
    val numbers = Regex("\\d+").findAll(text ?: "").take(4).map { it.value.toIntOrNull() ?: 0 }.toList()
    return numbers.ifEmpty { listOf(0) }
}

/** Like comparing two tuples in Python: number by number, a shorter list is smaller when the start is the same. */
fun compareVersions(first: String?, second: String?): Int {
    val a = versionTuple(first)
    val b = versionTuple(second)
    for (index in 0 until minOf(a.size, b.size)) {
        if (a[index] != b[index]) return a[index].compareTo(b[index])
    }
    return a.size.compareTo(b.size)
}

fun isNewerVersion(latest: String?, current: String?): Boolean = compareVersions(latest, current) > 0
