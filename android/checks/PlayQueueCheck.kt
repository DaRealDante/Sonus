import app.sonus.core.PlayQueue
import app.sonus.core.REPEAT_ALL
import app.sonus.core.REPEAT_OFF
import app.sonus.core.REPEAT_ONE
import kotlin.random.Random

class Item(val name: String) { override fun toString() = name }

var failures = 0
fun check(condition: Boolean, text: String) { if (!condition) { failures++; println("ERRORE: $text") } }

/** Dev check (not part of the app): the queue behaves like the PC player. */
fun main() {
    val items = (1..8).map { Item("s$it") }
    val queue = PlayQueue<Item>(Random(42))

    queue.playSongs(items, 3)
    check(queue.currentIndex == 3 && queue.current() === items[3], "start index without shuffle")
    check(queue.queue.map { it.name } == items.map { it.name }, "order without shuffle")

    // shuffle on: current stays, the songs before stay, the songs after are mixed (same set)
    queue.setShuffle(true)
    check(queue.current() === items[3] && queue.currentIndex == 3, "shuffle keeps the current song")
    check(queue.queue.subList(0, 4).map { it.name } == listOf("s1", "s2", "s3", "s4"), "shuffle keeps what is before")
    check(queue.queue.subList(4, 8).toSet() == items.subList(4, 8).toSet(), "shuffle keeps the same songs")
    // shuffle off: the original order comes back and the current song is found again
    queue.setShuffle(false)
    check(queue.queue.map { it.name } == items.map { it.name } && queue.current() === items[3], "shuffle off restores order")

    // playSongs with shuffle: the chosen song is first
    queue.playSongs(items, 5, shuffled = true)
    check(queue.currentIndex == 0 && queue.current() === items[5], "shuffled start: chosen first")
    check(queue.queue.toSet() == items.toSet(), "shuffled start: all songs present")

    // add / play next / remove / move
    queue.playSongs(items.subList(0, 4), 1, shuffled = false)
    val extra = Item("x1"); val extra2 = Item("x2")
    queue.playNext(listOf(extra))
    check(queue.queue.map { it.name } == listOf("s1", "s2", "x1", "s3", "s4"), "play next position")
    queue.addToQueue(listOf(extra2))
    check(queue.queue.last() === extra2, "add to end")
    queue.removeFromQueue(listOf(0, 1))   // index 1 is the current song: it stays
    check(queue.queue.map { it.name } == listOf("s2", "x1", "s3", "s4", "x2") && queue.current()!!.name == "s2" && queue.currentIndex == 0, "remove keeps current and fixes index")
    queue.moveInQueue(0, 3)
    check(queue.current()!!.name == "s2" && queue.currentIndex == 3, "move updates the current index")
    queue.clearUpcoming()
    check(queue.queue.size == 4 && queue.queue.last().name == "s2", "clear upcoming")

    // empty queue: add starts a new queue
    val empty = PlayQueue<Item>(Random(1))
    check(!empty.addToQueue(listOf(items[0], items[1])) && empty.currentIndex == 0 && empty.queue.size == 2, "add on empty queue")

    // repeat cycle like the PC: off -> all -> one -> off
    val modes = PlayQueue<Item>()
    val seen = mutableListOf(modes.repeatMode); repeat(3) { modes.cycleRepeat(); seen.add(modes.repeatMode) }
    check(seen == listOf(REPEAT_OFF, REPEAT_ALL, REPEAT_ONE, REPEAT_OFF), "repeat cycle")

    // wrap around with shuffle: first song is never the one that just played
    for (seed in 1..50) {
        val q = PlayQueue<Item>(Random(seed))
        q.playSongs(items, 0, shuffled = true)
        q.onAdvanced(q.queue.size - 1)
        val last = q.current()
        q.wrapAround()
        check(q.currentIndex == 0 && q.queue[0] !== last && q.queue.toSet() == items.toSet(), "wrap around seed $seed")
    }

    println(if (failures == 0) "PlayQueue: tutto ok" else "PlayQueue: $failures errori")
    if (failures > 0) kotlin.system.exitProcess(1)
}
