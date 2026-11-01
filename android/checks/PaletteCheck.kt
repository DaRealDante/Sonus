import app.sonus.core.Palette
import java.io.File

/** Dev check (not part of the app): the Kotlin palette must give the same colours as the PC app for every case. */
fun main(arguments: Array<String>) {
    var failures = 0
    var cases = 0
    File(arguments[0]).forEachLine { line ->
        val (customText, expectedText) = line.split("|")
        val custom = customText.split(";").filter { it.isNotBlank() }.associate { it.substringBefore("=") to it.substringAfter("=") }
        val expected = expectedText.split(";").associate { it.substringBefore("=") to it.substringAfter("=") }
        val actual = Palette.resolve(custom).toMap()
        cases++
        for ((key, value) in expected) {
            if (actual[key] != value) {
                failures++
                if (failures <= 15) println("DIVERSO  $custom  $key: PC=$value  Android=${actual[key]}")
            }
        }
    }
    println("$cases casi, $failures differenze")
    if (failures > 0) kotlin.system.exitProcess(1)
}
