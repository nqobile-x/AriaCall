"""UI contract: the markup, scripts and stylesheet must agree, and the basics of usability hold.

These are static checks (no browser). They catch the failures that make a UI feel broken:
a script looking for an element that no longer exists, unreadable text, tiny type, controls
that cannot be reached by keyboard, and a layout that pushes the message box off screen.
"""

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).parent.parent / "api" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
SCRIPTS = {name: (STATIC / name).read_text(encoding="utf-8") for name in ("app.js", "practice.js", "voice.js")}


def _lum(hex_colour):
    hex_colour = hex_colour.lstrip("#")
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def token(name):
    return re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", CSS).group(1)


class ScriptsMatchMarkup(unittest.TestCase):
    def defined_ids(self):
        ids = set(re.findall(r'\bid="([\w-]+)"', HTML))
        for source in SCRIPTS.values():
            ids |= set(re.findall(r'\bid="([\w-]+)"', source))
            ids |= set(re.findall(r"\.id\s*=\s*'([\w-]+)'", source))
        return ids

    def test_every_element_a_script_looks_up_exists(self):
        defined = self.defined_ids()
        missing = {}
        for name, source in SCRIPTS.items():
            used = set(re.findall(r"getElementById\(\s*['\"]([\w-]+)['\"]\s*\)", source))  # skips 'ob-step-' + n concatenations
            used |= set(re.findall(r"(?:querySelector|querySelectorAll|\$)\(\s*['\"`]#([\w-]+)", source))
            gone = sorted(i for i in used if i not in defined)
            if gone:
                missing[name] = gone
        self.assertEqual(missing, {}, "scripts reference ids that no markup defines")

    def test_static_classes_scripts_query_exist(self):
        for cls in ("mode-tab", "clang-btn", "clevel-btn", "vbtn", "suggestions", "pp-chip"):
            self.assertIn(cls, HTML, f".{cls} is queried by the scripts")

    def test_scripts_are_loaded_in_dependency_order(self):
        order = [HTML.index(f"/static/{n}") for n in ("voice.js", "app.js", "practice.js")]
        self.assertEqual(order, sorted(order))

    def test_service_worker_precaches_every_script(self):
        sw = (STATIC / "sw.js").read_text(encoding="utf-8")
        for name in ("app.js", "voice.js", "practice.js", "styles.css"):
            self.assertIn(f"/static/{name}", sw)


class MarkupBasics(unittest.TestCase):
    def test_no_stray_style_block_and_little_inline_styling(self):
        self.assertNotIn("<style", HTML, "styles belong in styles.css (a <style> after </head> is invalid HTML)")
        self.assertLessEqual(len(re.findall(r'\sstyle="', HTML)), 3)

    def test_every_button_declares_its_type(self):
        untyped = [m for m in re.findall(r"<button\b[^>]*>", HTML) if " type=" not in m]
        self.assertEqual(untyped, [])

    def test_tabs_are_an_accessible_tablist(self):
        self.assertIn('role="tablist"', HTML)
        tabs = re.findall(r'<button[^>]*role="tab"[^>]*>', HTML)
        self.assertEqual(len(tabs), 4)
        self.assertTrue(all("aria-selected" in t for t in tabs))
        self.assertEqual(sum('aria-selected="true"' in t for t in tabs), 1)

    def test_mobile_meta_and_language(self):
        self.assertIn('lang="en"', HTML)
        self.assertIn("viewport-fit=cover", HTML)
        self.assertIn('name="theme-color"', HTML)

    def test_fonts_do_not_block_rendering(self):
        self.assertNotIn("@import", CSS, "@import of web fonts blocks first paint on slow or offline connections")
        self.assertIn("media=\"print\"", HTML)

    def test_form_controls_have_labels(self):
        for control_id in ("message", "code-input", "lesson-select"):
            self.assertRegex(HTML, rf'for="{control_id}"|id="{control_id}"[^>]*aria-label|aria-label="[^"]+"[^>]*id="{control_id}"', control_id)

    def test_icon_only_buttons_are_named(self):
        for match in re.findall(r'<button[^>]*class="icon-btn[^>]*>', HTML):
            self.assertIn("aria-label", match)

    def test_status_and_live_regions_exist(self):
        for hint in ('id="status"', 'aria-live="polite"', 'role="status"'):
            self.assertIn(hint, HTML)


class LayoutFitsTheScreen(unittest.TestCase):
    def test_app_fills_the_viewport_and_regions_scroll_inside(self):
        self.assertRegex(CSS, r"\.app-shell\s*\{[^}]*height:\s*100dvh")
        self.assertRegex(CSS, r"body\s*\{[^}]*overflow:\s*hidden")
        self.assertRegex(CSS, r"\.conversation\s*\{[^}]*flex:\s*1[^}]*min-height:\s*0[^}]*overflow-y:\s*auto")
        self.assertRegex(CSS, r"\.panel\s*\{[^}]*overflow-y:\s*auto")

    def test_no_fixed_minimum_heights_that_push_the_composer_off_screen(self):
        self.assertNotRegex(CSS, r"min-height:\s*(4[5-9]\d|5\d\d|6\d\d)px")

    def test_phones_get_a_bottom_tab_bar_that_reserves_space(self):
        block = CSS[CSS.index("@media (max-width: 720px)"):]
        self.assertRegex(block, r"\.tabs\s*\{[^}]*position:\s*fixed[^}]*bottom:\s*0")
        self.assertIn("safe-area-inset-bottom", CSS)
        self.assertRegex(block, r"\.app-shell\s*\{[^}]*padding-bottom")

    def test_touch_targets_grow_on_touch_devices(self):
        self.assertIn("@media (pointer: coarse)", CSS)
        self.assertRegex(CSS, r"pointer: coarse\)[\s\S]*\.btn\s*\{[^}]*min-height:\s*44px")

    def test_two_column_code_panel_stacks_on_narrow_screens(self):
        self.assertRegex(CSS, r"@media \(max-width: 900px\)\s*\{[^}]*\.code-layout\s*\{[^}]*grid-template-columns:\s*1fr\s*;")

    def test_closed_call_panel_is_not_focusable(self):
        self.assertRegex(CSS, r"\.call-panel\s*\{[^}]*visibility:\s*hidden")
        self.assertRegex(CSS, r"\.call-panel\.open\s*\{[^}]*visibility:\s*visible")

    def test_hover_effects_only_where_hover_exists(self):
        self.assertIn("@media (hover: hover)", CSS)

    def test_focus_and_reduced_motion_are_handled(self):
        self.assertIn(":focus-visible", CSS)
        self.assertIn("prefers-reduced-motion: reduce", CSS)


class ReadableAndAccessible(unittest.TestCase):
    def test_secondary_text_meets_wcag_aa(self):
        bg, surface = token("bg"), token("surface")
        for name in ("text", "text-2", "text-3", "good", "warn", "bad", "accent"):
            for background in (bg, surface):
                self.assertGreaterEqual(contrast(token(name), background), 4.5, f"--{name} on {background}")

    def test_button_text_is_readable_on_accent(self):
        self.assertGreaterEqual(contrast(token("accent-ink"), token("accent")), 4.5)

    def test_no_tiny_type(self):
        sizes = []
        for decl in re.findall(r"font(?:-size)?:\s*([^;}]+)", CSS):
            if decl.strip().startswith("0"):
                continue  # the phone status dot intentionally hides its label
            m = re.search(r"(?<![\w.-])(\d+(?:\.\d+)?)px", decl)
            if m:
                sizes.append(float(m.group(1)))
        self.assertTrue(sizes)
        self.assertGreaterEqual(min(sizes), 11, f"smallest font size is {min(sizes)}px")

    def test_inputs_are_16px_or_more_on_phones_so_ios_does_not_zoom(self):
        self.assertRegex(CSS, r"\.field\s*\{[^}]*font:\s*15px")  # 15px is only used inside cards; the composer is larger
        self.assertRegex(CSS, r"\.composer textarea\s*\{[^}]*font:\s*400\s*(1[6-9]|2\d)px")
        self.assertRegex(CSS, r"@media \(max-width: 720px\)[\s\S]*\.composer textarea\s*\{\s*font-size:\s*1[6-9]px")

    def test_speech_highlight_styles_exist_with_a_fallback(self):
        self.assertIn("::highlight(spk-sentence)", CSS)
        self.assertIn("::highlight(spk-word)", CSS)
        self.assertIn(".spk-block", CSS)

    def test_server_supplied_text_is_never_interpolated_raw(self):
        """Challenge text, test messages and model output must pass through esc()/fmt() before innerHTML."""
        raw_patterns = [
            r"\$\{c\.(title|prompt|starter|hints\[[^\]]*\])\}",
            r"\$\{x\.(name|message|description)\}",
            r"\$\{r\.(error|stdout|explanation|solution)\}",
            r"\$\{o\}",
            r"\$\{n\.message\}",
        ]
        for name in ("practice.js", "app.js"):
            for line in SCRIPTS[name].splitlines():
                if "question" in line:  # plain text sent to the server, never inserted into the page
                    continue
                for pattern in raw_patterns:
                    self.assertIsNone(re.search(pattern, line), f"{name}: unescaped value on: {line.strip()[:100]}")

    def test_markdown_renderer_escapes_before_it_adds_markup(self):
        source = SCRIPTS["app.js"]
        self.assertIn("const h = escapeHtml(line)", source)
        self.assertIn("escapeHtml(body)", source)


class ListenAlongIsWiredIn(unittest.TestCase):
    def test_all_three_sections_can_be_listened_to_and_asked_by_voice(self):
        app, practice = SCRIPTS["app.js"], SCRIPTS["practice.js"]
        self.assertIn("Voice?.addListen(document.getElementById('code-output'))", app)
        self.assertIn("code-voice-btn", app)
        self.assertIn('data-act="voice"', app)
        self.assertIn("Voice?.addListen(output.querySelector('#data-mentor'))", app)
        self.assertIn("window.Voice?.addListen(listen)", practice)
        self.assertIn('id="pr-voice"', practice)

    def test_answers_are_read_when_ready(self):
        self.assertIn("Voice?.onContentReady(listenRoot, output)", SCRIPTS["app.js"])
        self.assertIn("Voice?.onContentReady(listen, out)", SCRIPTS["practice.js"])

    def test_switching_section_stops_speech(self):
        self.assertRegex(SCRIPTS["app.js"], r"function switchMode\(mode\)\s*\{\s*window\.Voice\?\.stop\(true\)")

    def test_the_microphone_is_never_open_while_aria_speaks(self):
        self.assertRegex(SCRIPTS["voice.js"], r"stop\(true\);\s*//\s*never let Aria's own voice into the microphone")

    def test_listen_bar_offers_speed_voice_and_auto_read(self):
        source = SCRIPTS["voice.js"]
        for hint in ("listen-rate", "listen-voice", "listen-auto", "listen-stop", "aria-pressed"):
            self.assertIn(hint, source)

    def test_unsupported_browsers_get_a_message_not_a_broken_button(self):
        self.assertIn("Listening is not supported in this browser", SCRIPTS["voice.js"])
        self.assertIn("Voice questions need Chrome, Edge or Safari", SCRIPTS["voice.js"])


class VoicePanelIsFloatingAndMovable(unittest.TestCase):
    """'Ask by voice' opens a panel like the call panel: draggable, minimisable, remembered."""

    def test_every_section_opens_the_same_panel_through_voice_ask(self):
        self.assertIn("window.Voice?.ask(button, status", SCRIPTS["app.js"])           # Code
        self.assertIn("window.Voice?.ask(btn, status", SCRIPTS["app.js"])              # Data
        self.assertIn("window.Voice?.ask($('#pr-voice')", SCRIPTS["practice.js"])      # Practice
        self.assertRegex(SCRIPTS["voice.js"], r"function ask\([\s\S]*?openPanel\(\)")

    def test_panel_can_be_dragged_by_mouse_touch_and_keyboard(self):
        source = SCRIPTS["voice.js"]
        for hint in ("pointerdown", "pointermove", "pointerup", "setPointerCapture", "ArrowLeft", "ArrowDown"):
            self.assertIn(hint, source)
        self.assertRegex(CSS, r"\.vp-top\s*\{[^}]*touch-action:\s*none")     # a finger drags the panel, not the page
        self.assertRegex(CSS, r"\.vp-top\s*\{[^}]*cursor:\s*grab")

    def test_a_tap_is_not_mistaken_for_a_drag(self):
        self.assertRegex(SCRIPTS["voice.js"], r"Math\.hypot\([^)]*\)\s*<\s*4")

    def test_panel_can_be_minimised_to_a_pill_expanded_and_closed(self):
        source = SCRIPTS["voice.js"]
        for hint in ("vp-min", "vp-close", "is-minimized", "setMinimized", "Expand voice panel", "Minimise voice panel", "Escape"):
            self.assertIn(hint, source)
        self.assertIn(".voice-panel.is-minimized", CSS)
        self.assertRegex(CSS, r"\.voice-panel\.is-minimized \.vp-body\s*\{\s*display:\s*none")

    def test_position_and_preferences_survive_a_reload(self):
        source = SCRIPTS["voice.js"]
        self.assertIn("aria-voice-panel", source)
        self.assertIn("savePanelPrefs", source)
        self.assertIn("minimized: panel.minimized, convo: panel.convo", source)

    def test_clamping_never_uses_the_rect_of_a_hidden_panel(self):
        """Regression: a hidden panel measures 0x0, which snapped a restored panel to the top-left corner."""
        body = SCRIPTS["voice.js"][SCRIPTS["voice.js"].index("function clampToViewport()"):SCRIPTS["voice.js"].index("function placeAt(")]
        self.assertIn("parseFloat(el.style.left)", body)
        self.assertNotIn("getBoundingClientRect", body)

    def test_panel_stacks_between_the_tab_bar_and_the_call_panel(self):
        z = lambda selector: int(re.search(rf"{re.escape(selector)}\s*\{{[^}}]*z-index:\s*(\d+)", CSS).group(1))
        self.assertGreater(z(".voice-panel"), z(".tabs"))
        self.assertLess(z(".voice-panel"), z(".call-panel"))

    def test_on_phones_it_starts_above_the_tab_bar_and_fits_the_width(self):
        block = CSS[CSS.index("@media (max-width: 720px)", CSS.index(".voice-panel {")):]
        self.assertRegex(block, r"\.voice-panel\s*\{[^}]*bottom:\s*calc\(76px \+ var\(--safe-b\)\)[^}]*width:\s*min\(340px, calc\(100vw - 24px\)\)")

    def test_entrance_animation_plays_once_not_after_every_drag(self):
        self.assertRegex(CSS, r"\.voice-panel\.vp-enter\s*\{[^}]*animation")
        self.assertNotRegex(CSS, r"\.voice-panel\s*\{[^}]*animation")

    def test_panel_shows_what_is_heard_and_the_sentence_being_read(self):
        source = SCRIPTS["voice.js"]
        for hint in ("vp-quote", "vp-now", "panelSentence", "setPanelState('thinking'", "setPanelState('speaking'", "setPanelState('listening'"):
            self.assertIn(hint, source)

    def test_hands_free_conversation_mode_exists_and_waits_for_aria_to_finish(self):
        source = SCRIPTS["voice.js"]
        self.assertIn("Keep the conversation going", source)
        self.assertRegex(source, r"function panelSpeechEnded\(\)[\s\S]*panel\.convo[\s\S]*micPressed\(\)")
        self.assertIn("!state.session", source)   # never open the mic while Aria is still talking

    def test_user_text_only_ever_enters_the_panel_as_text(self):
        source = SCRIPTS["voice.js"]
        self.assertIn(".textContent = info.text", source)
        self.assertIn("quote.textContent", source)
        self.assertNotRegex(source, r"vp-(state|quote|now)[^\n]*innerHTML")

    def test_leaving_the_section_or_closing_stops_the_microphone_and_speech(self):
        self.assertRegex(SCRIPTS["app.js"], r"function switchMode\(mode\)\s*\{\s*window\.Voice\?\.stop\(true\);\s*window\.Voice\?\.closePanel\(\)")
        self.assertRegex(SCRIPTS["voice.js"], r"function closePanel\(\)[\s\S]*recognition\.abort\(\)[\s\S]*stop\(true\)")

    def test_unsupported_browsers_see_an_explanation_inside_the_panel(self):
        self.assertRegex(SCRIPTS["voice.js"], r"Voice questions need Chrome, Edge or Safari[\s\S]*setPanelState\('error'")


if __name__ == "__main__":
    unittest.main()
