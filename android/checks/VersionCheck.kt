import app.sonus.core.compareVersions
import java.io.File

/** Dev check (not part of the app): comparing versions gives the same answer as the PC app. */
fun main(arguments: Array<String>) {
    var failures = 0
    var cases = 0
    File(arguments[0]).forEachLine { line ->
        val parts = line.split("|")
        val expected = parts[2].toInt()
        val actual = compareVersions(parts[0], parts[1]).let { if (it > 0) 1 else if (it < 0) -1 else 0 }
        cases++
        if (actual != expected) {
            failures++
            if (failures <= 10) println("DIVERSO '${parts[0]}' vs '${parts[1]}': PC=$expected Android=$actual")
        }
    }
    println("$cases casi, $failures differenze")
    if (failures > 0) kotlin.system.exitProcess(1)
}
