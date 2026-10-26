package it.sonus.mobile

import org.json.JSONObject

/** Published objects are immutable. Nested objects are complete backend snapshots. */
internal object HostState {
    fun merge(previous: JSONObject, update: JSONObject): JSONObject {
        val result = JSONObject()
        previous.keys().forEach { key -> result.put(key, previous.get(key)) }
        update.keys().forEach { key ->
            if (key != "tick" && key != "patch") result.put(key, update.get(key))
        }
        return result
    }
}
