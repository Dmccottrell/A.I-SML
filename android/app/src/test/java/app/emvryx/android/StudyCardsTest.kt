package app.emvryx.android

import app.emvryx.android.ui.StudyCards
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** study_cards: which replies get the Practise button (the same answers as tests/test_study_cards.py on the server) */
class StudyCardsTest {
    @Test
    fun numberedLinesBulletsAndBoldTermsAreCards() {
        assertTrue(StudyCards.hasCards("Here you go:\n\n1. Photosynthesis: how a plant makes food\n2. **Chlorophyll**: the green stuff\n- Xylem: tubes for water"))
        assertTrue(StudyCards.hasCards("1) Stomata - tiny holes\n2) Root — holds the plant\n3) Leaf: catches light"))
    }

    @Test
    fun aTableIsCardsWithoutItsDashRow() {
        assertTrue(StudyCards.hasCards("| Term | Meaning |\n|---|---|\n| Noun | a naming word |\n| Verb | a doing word |"))
        assertFalse(StudyCards.hasCards("| Term | Meaning |\n|---|---|\n| Noun | a naming word |"))
    }

    @Test
    fun anOrdinaryAnswerIsNotADeck() {
        assertFalse(StudyCards.hasCards("The answer is simple: plants need light.\n\n1. Step one: water it\n2. Then wait"))
        assertFalse(StudyCards.hasCards(""))
    }

    @Test
    fun theWebsiteCallNamesTheChatAndTheMessage() {
        assertEquals("studyFromChat(12, 34)", StudyCards.practiseJs(12, 34))
    }
}
