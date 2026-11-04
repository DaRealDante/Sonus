package app.sonus.core

import kotlin.random.Random

const val REPEAT_OFF = 0
const val REPEAT_ALL = 1
const val REPEAT_ONE = 2

/**
 * Port of the queue logic of app/player.py (no Android code). Items are compared by identity (===): pass a distinct
 * object for every entry, so the same song can be in the queue twice.
 * Shuffle works like on the PC: the song that plays now stays first, the songs after it are mixed;
 * turning shuffle off brings back the original order.
 */
class PlayQueue<T : Any>(private val random: Random = Random.Default) {
    var queue: MutableList<T> = mutableListOf()
        private set
    private var original: MutableList<T> = mutableListOf()
    var currentIndex: Int = -1
        private set
    var shuffle: Boolean = false
        private set
    var repeatMode: Int = REPEAT_OFF
        private set

    fun current(): T? = queue.getOrNull(currentIndex)

    /** Starts a new queue. With shuffle on, [startIndex] plays first and the rest is mixed. */
    fun playSongs(items: List<T>, startIndex: Int? = 0, shuffled: Boolean? = null) {
        if (items.isEmpty()) return
        if (shuffled != null) shuffle = shuffled
        original = items.toMutableList()
        val startItem = if (startIndex != null && startIndex in items.indices) items[startIndex] else null
        if (shuffle) {
            val first = startItem ?: items[random.nextInt(items.size)]
            val remaining = items.filter { it !== first }.toMutableList()
            remaining.shuffle(random)
            queue = (listOf(first) + remaining).toMutableList()
            currentIndex = 0
        } else {
            queue = items.toMutableList()
            currentIndex = startIndex ?: 0
        }
    }

    /** False when the queue was empty: then it starts as a new queue (the caller must start playing). */
    fun addToQueue(items: List<T>): Boolean {
        if (items.isEmpty()) return true
        if (queue.isEmpty()) {
            playSongs(items, 0)
            return false
        }
        queue.addAll(items)
        original.addAll(items)
        return true
    }

    fun playNext(items: List<T>): Boolean {
        if (items.isEmpty()) return true
        if (queue.isEmpty()) {
            playSongs(items, 0)
            return false
        }
        queue.addAll(currentIndex + 1, items)
        original.addAll(items)
        return true
    }

    /** The song that plays now cannot be removed. */
    fun removeFromQueue(indexes: Collection<Int>) {
        for (index in indexes.toSortedSet().reversed()) {
            if (index == currentIndex || index !in queue.indices) continue
            val removed = queue.removeAt(index)
            val originalIndex = original.indexOfFirst { it === removed }
            if (originalIndex >= 0) original.removeAt(originalIndex)
            if (index < currentIndex) currentIndex -= 1
        }
    }

    fun moveInQueue(fromIndex: Int, toIndex: Int) {
        if (fromIndex !in queue.indices) return
        val target = toIndex.coerceIn(0, queue.size - 1)
        val currentItem = current()
        val item = queue.removeAt(fromIndex)
        queue.add(target, item)
        if (currentItem != null) currentIndex = queue.indexOfFirst { it === currentItem }
    }

    fun clearUpcoming() {
        if (currentIndex >= 0) {
            queue = queue.subList(0, currentIndex + 1).toMutableList()
            original = queue.toMutableList()
        }
    }

    fun jumpTo(index: Int): Boolean {
        if (index !in queue.indices) return false
        currentIndex = index
        return true
    }

    fun setShuffle(enabled: Boolean) {
        if (enabled == shuffle) return
        shuffle = enabled
        val currentItem = current()
        if (queue.isEmpty()) return
        if (enabled) {
            val upcoming = queue.subList(currentIndex + 1, queue.size).toMutableList()
            upcoming.shuffle(random)
            queue = (queue.subList(0, currentIndex + 1) + upcoming).toMutableList()
        } else {
            queue = original.toMutableList()
            currentIndex = if (currentItem == null) 0 else queue.indexOfFirst { it === currentItem }.coerceAtLeast(0)
        }
    }

    fun cycleRepeat() {
        repeatMode = (repeatMode + 1) % 3
    }

    fun setRepeat(mode: Int) {
        repeatMode = mode
    }

    /**
     * The queue is over and the first song comes again (repeat all, or "next" pressed on the last song).
     * With shuffle the queue is mixed again, and the song that just played does not come first again.
     */
    fun wrapAround() {
        if (queue.isEmpty()) return
        if (shuffle && queue.size > 1) {
            val current = current()
            queue.shuffle(random)
            if (queue[0] === current) queue.add(queue.removeAt(0))
        }
        currentIndex = 0
    }

    /** Called when the player goes by itself to the next song. */
    fun onAdvanced(newIndex: Int) {
        if (newIndex in queue.indices) currentIndex = newIndex
    }

    /** Restores a saved queue (nothing starts). */
    fun restore(items: List<T>, index: Int) {
        if (items.isEmpty()) return
        queue = items.toMutableList()
        original = items.toMutableList()
        currentIndex = index.coerceIn(0, items.size - 1)
    }

    fun clear() {
        queue = mutableListOf()
        original = mutableListOf()
        currentIndex = -1
    }
}
