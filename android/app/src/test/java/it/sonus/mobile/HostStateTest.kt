package it.sonus.mobile

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class HostStateTest {
    @Test fun positionTickPreservesLibraryAndMetadata() {
        val old = JSONObject("""{"songs":[{"id":7}],"current":{"title":"One"},"position":0}""")
        val result = HostState.merge(old, JSONObject("""{"tick":true,"position":2450,"playing":true}"""))
        assertEquals(7, result.getJSONArray("songs").getJSONObject(0).getInt("id"))
        assertEquals("One", result.getJSONObject("current").getString("title"))
        assertEquals(2450, result.getInt("position"))
        assertFalse(result.has("tick"))
        assertEquals(0, old.getInt("position"))
    }

    @Test fun explicitEmptyCollectionsAndNullReplacePreviousValues() {
        val result = HostState.merge(JSONObject("""{"queue":[1],"current":{"id":1}}"""),
            JSONObject("""{"queue":[],"current":null}"""))
        assertEquals(0, result.getJSONArray("queue").length())
        assertTrue(result.isNull("current"))
    }

    @Test fun completeNestedSnapshotsRemoveDeletedPresets() {
        val result = HostState.merge(JSONObject("""{"eq":{"customPresets":{"Removed":[1],"Kept":[2]}}}"""),
            JSONObject("""{"eq":{"customPresets":{"Kept":[2]}}}"""))
        assertFalse(result.getJSONObject("eq").getJSONObject("customPresets").has("Removed"))
        assertEquals(2, result.getJSONObject("eq").getJSONObject("customPresets").getJSONArray("Kept").getInt(0))
    }
}
