package it.sonus.mobile

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertTrue

class MobileUiTest {
    @get:Rule val rule = createComposeRule()

    private val song = JSONObject().put("id", 1).put("title", "Brano di prova").put("artist", "Artista").put("duration", 180)
    private fun show(): MutableList<String> {
        val commands = mutableListOf<String>()
        val state = JSONObject().put("ready", true).put("songs", JSONArray().put(song))
            .put("current", song).put("queue", JSONArray().put(song)).put("duration", 180000)
        rule.setContent { MaterialTheme { SonusApp(state, { action, _ -> commands.add(action) }, {}, {}, {}) } }
        return commands
    }

    @Test fun mobileNavigationKeepsMiniPlayerAvailable() {
        show()
        listOf("Cerca", "Libreria", "Scopri", "Home").forEach {
            rule.onNodeWithTag("nav_$it").performClick()
            rule.onNodeWithTag("mini_player").assertIsDisplayed()
        }
    }

    @Test fun playerControlsSendPlaybackActions() {
        val commands = show()
        rule.onNodeWithTag("mini_player").performClick()
        rule.onNodeWithContentDescription("Brano successivo").performClick()
        assertTrue(commands.contains("next"))
        rule.onNodeWithContentDescription("Riproduci o pausa").performClick()
        assertTrue(commands.contains("toggle"))
    }

    @Test fun searchAcceptsTextAndStartsSearch() {
        val commands = show()
        rule.onNodeWithTag("nav_Cerca").performClick()
        rule.onNodeWithTag("search_input").performTextInput("musica")
        rule.onNodeWithTag("search_submit").performClick()
        assertTrue(commands.contains("search"))
    }

    @Test fun everyAdvancedAreaIsReachableFromPlayer() {
        show()
        rule.onNodeWithTag("mini_player").performClick()
        listOf("Coda", "Effetti", "Equalizzatore", "Loop e taglio", "Testi", "Video", "Stanza").forEach { title ->
            rule.onNodeWithText(title).performScrollTo().assertIsDisplayed()
        }
    }
}
