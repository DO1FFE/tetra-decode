"""Sprachwahl und laufende Oberfläche ohne SDR-Hardware prüfen.

Aufruf: python -m unittest discover -s tests -v
Alle Benutzerdateien entstehen in einem temporären Profil. Externe Programme,
Installationen, Audiogeräte und Telegram sind während der GUI-Tests gesperrt.
"""

from contextlib import ExitStack, redirect_stderr
import importlib
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import übersetzungen as texte


class SprachwahlTests(unittest.TestCase):
    def tearDown(self):
        texte.sprache_festlegen("de")

    def test_systemsprache_und_internationaler_standard(self):
        for systemsprache, erwartet in (
            ("de_DE", "de"), ("de-DE", "de"), ("de_AT", "de"),
            ("de_CH", "de"), ("DE_de.UTF-8", "de"), ("en_GB", "en"),
            ("en_US", "en"), ("pt_PT", "en"), ("fr_FR", "en"), ("", "en"),
        ):
            with self.subTest(systemsprache=systemsprache):
                self.assertEqual(
                    texte.startsprache(argumente=[], systemsprache=systemsprache),
                    erwartet,
                )

    def test_gespeicherte_wahl_hat_vorrang_vor_systemsprache(self):
        for gespeichert, systemsprache in (("en", "de_DE"), ("de", "pt_PT")):
            with self.subTest(gespeichert=gespeichert):
                self.assertEqual(
                    texte.startsprache(gespeichert, [], systemsprache), gespeichert
                )

    def test_ungültige_altkonfiguration_verwendet_systemsprache(self):
        for gespeichert in (None, "", "pt", "EN", 23):
            with self.subTest(gespeichert=gespeichert):
                self.assertEqual(texte.startsprache(gespeichert, [], "de_DE"), "de")
                self.assertEqual(texte.startsprache(gespeichert, [], "pt_PT"), "en")

    def test_cli_alias_und_gleichheitszeichen_haben_höchste_priorität(self):
        for option in ("--language", "--sprache"):
            for sprache in ("de", "en"):
                for argumente in ([option, sprache], [f"{option}={sprache}"]):
                    with self.subTest(argumente=argumente):
                        self.assertEqual(
                            texte.startsprache(
                                "en" if sprache == "de" else "de",
                                ["--cli", *argumente, "--ppm", "7"], "pt_PT",
                            ),
                            sprache,
                        )

    def test_cli_fehler_werden_nicht_still_ignoriert(self):
        for argumente in (["--language", "pt"], ["--sprache"], ["--language="]):
            with self.subTest(argumente=argumente), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as fehler:
                    texte.startsprache("de", argumente, "pt_PT")
                self.assertEqual(fehler.exception.code, 2)

    def test_explizite_argumente_verhindern_zugriff_auf_testprogramm_argumente(self):
        with mock.patch.object(sys, "argv", ["programm", "--language", "en"]):
            self.assertEqual(texte.startsprache(None, [], "de_DE"), "de")
            self.assertEqual(texte.startsprache(None, None, "de_DE"), "en")

    def test_sprachwechsel_und_unbekannte_rohdaten(self):
        rohtext = "TESTSTATION ÄÖÜß {unbekannt}: 395.625 MHz"
        texte.sprache_festlegen("en")
        self.assertEqual(texte.aktuelle_sprache(), "en")
        self.assertEqual(texte.übersetzen("Einstellungen"), "Settings")
        self.assertEqual(texte.übersetzen(rohtext), rohtext)
        texte.sprache_festlegen("de")
        self.assertEqual(texte.übersetzen("Einstellungen"), "Einstellungen")
        with self.assertRaises(ValueError):
            texte.sprache_festlegen("pt")
        self.assertEqual(texte.aktuelle_sprache(), "de")

    def test_platzhalter_formatierung_und_gerätedaten_bleiben_erhalten(self):
        texte.sprache_festlegen("en")
        self.assertEqual(
            texte.übersetzen("Frequenz: {wert0:.3f} MHz", wert0=395.625),
            "Frequency: 395.625 MHz",
        )
        gerät = "Einstellungen {RTL-SDR} ÄÖÜß"
        self.assertEqual(
            texte.übersetzen("Konnte {wert0} nicht ausführen: {wert1}",
                             wert0=gerät, wert1="Fehler {Code}"),
            f"Could not run {gerät}: Fehler {{Code}}",
        )

    def test_copyright_im_erstellungsjahr_und_folgejahr(self):
        self.assertEqual(texte.copyright_text(2026), "© 2026 Erik Schauer, do1ffe@darc.de")
        self.assertEqual(texte.copyright_text(2027), "© 2026 - 2027 Erik Schauer, do1ffe@darc.de")


class OberflächeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.umgebung = ExitStack()
        cls.addClassCleanup(cls.umgebung.close)
        cls.profil = Path(cls.umgebung.enter_context(tempfile.TemporaryDirectory()))
        cls.umgebung.enter_context(mock.patch.dict(os.environ, {
            "HOME": str(cls.profil), "USERPROFILE": str(cls.profil),
            "QT_QPA_PLATFORM": "offscreen", "MPLCONFIGDIR": str(cls.profil / "matplotlib"),
        }))
        cls.umgebung.enter_context(mock.patch.object(sys, "argv", ["sprachtests"]))
        cls.gui = importlib.import_module("sdr_gui")
        cls.anwendung = cls.gui.QtWidgets.QApplication.instance()
        if cls.anwendung is None:
            cls.anwendung = cls.gui.QtWidgets.QApplication(["sprachtests"])
        cls.anwendung.setQuitOnLastWindowClosed(False)
        cls.umgebung.enter_context(mock.patch.object(cls.gui, "CONFIG_FILE", str(cls.profil / "konfiguration.json")))
        cls.addClassCleanup(cls._protokoll_schließen)

    @classmethod
    def _protokoll_schließen(cls):
        # Windows kann temporäre Dateien nur nach dem Schließen des Handlers löschen.
        for protokoll in list(cls.gui.logger.handlers):
            dateiname = getattr(protokoll, "baseFilename", "")
            if dateiname and Path(dateiname).is_relative_to(cls.profil):
                cls.gui.logger.removeHandler(protokoll)
                protokoll.close()

    def setUp(self):
        self.sperren = ExitStack()
        self.addCleanup(self.sperren.close)
        self.addCleanup(texte.sprache_festlegen, "de")
        texte.sprache_festlegen("de")
        self.fenster = []
        self.addCleanup(self._fenster_schließen)
        self.gui.save_config({
            "language": "de", "ui_profile_version": 3,
            "calibrate_on_start": False, "scheduler_enabled": False,
        })
        for name in ("Popen", "run", "check_call", "check_output"):
            self.sperren.enter_context(mock.patch.object(
                self.gui.subprocess, name,
                side_effect=AssertionError("Externe Programme sind im Sprachtest gesperrt."),
            ))
        self.sperren.enter_context(mock.patch.object(
            self.gui.pyaudio, "PyAudio", side_effect=AssertionError("Audiogeräte sind gesperrt.")
        ))
        self.sperren.enter_context(mock.patch.object(
            self.gui.SetupWorker, "detect_missing_requirements", return_value=([], [], [])
        ))
        self.sperren.enter_context(mock.patch.object(self.gui.SetupWorker, "decoder_notice", return_value=None))
        for klasse in (
            self.gui.SetupWorker, self.gui.CalibrationWorker, self.gui.TetraSignalSearchWorker,
            self.gui.SDRScanner, self.gui.TetraDecoder, self.gui.AudioPlayer,
            self.gui.DecodedAudioPlayer,
        ):
            self.sperren.enter_context(mock.patch.object(
                klasse, "start", side_effect=AssertionError("Worker und Hardwarestarts sind gesperrt.")
            ))
        for name in (
            "_wsl_tetra_audio_backend_available", "_wsl_osmo_decoder_available",
            "_official_osmo_decoder_available", "_native_osmo_tools_available",
            "_legacy_osmo_decoder_available", "_legacy_audio_decoder_available",
        ):
            self.sperren.enter_context(mock.patch.object(self.gui, name, return_value=False))
        self.sperren.enter_context(mock.patch.object(self.gui, "_available_gain_values", return_value=[0.0, 14.4, 49.6]))
        self.sperren.enter_context(mock.patch.object(
            self.gui, "list_sdr_devices", return_value=[("Testgerät ÄÖÜß", 0), ("Einstellungen", 1)]
        ))
        self.sperren.enter_context(mock.patch.object(self.gui.QtCore.QTimer, "singleShot", return_value=None))
        self.sperren.enter_context(mock.patch.object(
            self.gui.MainWindow, "send_telegram", side_effect=AssertionError("Telegram ist gesperrt.")
        ))
        if self.gui.requests is not None:
            self.sperren.enter_context(mock.patch.object(
                self.gui.requests.sessions.Session, "request",
                side_effect=AssertionError("Netzwerkzugriffe sind gesperrt."),
            ))

    def _fenster_schließen(self):
        for fenster in reversed(self.fenster):
            fenster.close()
            fenster.deleteLater()
        self.anwendung.processEvents()

    def _neues_fenster(self):
        fenster = self.gui.MainWindow()
        self.fenster.append(fenster)
        self.anwendung.processEvents()
        return fenster

    def _sprache_wechseln(self, fenster, sprache):
        index = fenster.sprachwahl.findData(sprache)
        self.assertGreaterEqual(index, 0, "Die Sprachwahl muss stabile Sprachcodes enthalten.")
        fenster.sprachwahl.setCurrentIndex(index)
        self.anwendung.processEvents()
        self.assertEqual(texte.aktuelle_sprache(), sprache)

    def test_beschriftungen_tabellen_achsen_und_footer(self):
        fenster = self._neues_fenster()
        self.assertEqual(fenster.tabs.tabText(0), "Übersicht")
        self.assertEqual(fenster.canvas.ax.get_xlabel(), "Frequenz [Hz]")
        self._sprache_wechseln(fenster, "en")
        self.assertEqual(fenster.tabs.tabText(0), "Overview")
        self.assertEqual(fenster.tabs.tabText(6), "Settings")
        self.assertEqual(fenster.start_btn.text(), "Start")
        self.assertEqual(fenster.overview_monitor_btn.text(), "Start monitoring")
        self.assertEqual(fenster.overview_channel_table.horizontalHeaderItem(0).text(), "Frequency")
        self.assertEqual(fenster.talkgroup_table.horizontalHeaderItem(3).text(), "Hits")
        self.assertEqual(fenster.decoder_data_table.horizontalHeaderItem(3).text(), "Content")
        self.assertEqual(fenster.canvas.ax.get_xlabel(), "Frequency [Hz]")
        self.assertEqual(fenster.canvas.ax.get_ylabel(), "Power [dB]")
        self.assertIn("Erik Schauer, do1ffe@darc.de", fenster.footer_label.text())
        self.assertIn("©", fenster.footer_label.text())
        self._sprache_wechseln(fenster, "de")
        self.assertEqual(fenster.tabs.tabText(0), "Übersicht")
        self.assertEqual(fenster.start_btn.text(), "Starten")
        self.assertEqual(fenster.canvas.ax.get_xlabel(), "Frequenz [Hz]")

    def test_benutzereingaben_auswahl_und_aktive_objekte_bleiben_erhalten(self):
        fenster = self._neues_fenster()
        fenster.filter_edit.setText("Überwachung starten")
        fenster.token_edit.setText("Einstellungen")
        fenster.chat_edit.setText("-123456789")
        fenster.ppm_spin.setValue(17)
        fenster.device_box.setCurrentIndex(1)
        fenster.freq_range_box.setCurrentIndex(1)
        fenster.audio_mode_combo.setCurrentIndex(fenster.audio_mode_combo.findData("always"))
        fenster.tabs.setCurrentIndex(2)
        fenster.tetra_output.setPlainText("Decoder-Rohdaten: Einstellungen ÄÖÜß")
        fenster.scanner._running.set()
        fenster.decoder._running.set()
        objekte = (fenster.scanner, fenster.decoder, fenster.player, fenster.dec_audio_player,
                   fenster.tabs, fenster.filter_edit, fenster.canvas)
        bereich = fenster.freq_range_box.currentData()
        with ExitStack() as laufende_objekte:
            stopps = [laufende_objekte.enter_context(mock.patch.object(objekt, "stop"))
                      for objekt in objekte[:4]]
            for sprache in ("en", "de", "en"):
                self._sprache_wechseln(fenster, sprache)
                self.assertEqual(fenster.filter_edit.text(), "Überwachung starten")
                self.assertEqual(fenster.token_edit.text(), "Einstellungen")
                self.assertEqual(fenster.chat_edit.text(), "-123456789")
                self.assertEqual(fenster.ppm_spin.value(), 17)
                self.assertEqual(fenster.device_box.currentText(), "Einstellungen")
                self.assertEqual(fenster.device_box.currentData(), 1)
                self.assertEqual(fenster.dashboard_device_value.text(), "Einstellungen")
                self.assertEqual(fenster.freq_range_box.currentData(), bereich)
                self.assertEqual(fenster.audio_mode_combo.currentData(), "always")
                self.assertEqual(fenster.tabs.currentIndex(), 2)
                self.assertEqual(fenster.tetra_output.toPlainText(), "Decoder-Rohdaten: Einstellungen ÄÖÜß")
                self.assertEqual(objekte, (fenster.scanner, fenster.decoder, fenster.player,
                                          fenster.dec_audio_player, fenster.tabs,
                                          fenster.filter_edit, fenster.canvas))
                self.assertTrue(fenster.scanner._running.is_set())
                self.assertTrue(fenster.decoder._running.is_set())
            for stopp in stopps:
                stopp.assert_not_called()

    def test_sprachwahl_und_frequenzbereich_überleben_neustart(self):
        fenster = self._neues_fenster()
        fenster.freq_range_box.setCurrentIndex(2)
        bereich = fenster.freq_range_box.currentData()
        fenster.ppm_spin.setValue(-12)
        self._sprache_wechseln(fenster, "en")
        fenster.close()
        gespeichert = json.loads(Path(self.gui.CONFIG_FILE).read_text(encoding="utf-8"))
        self.assertEqual(gespeichert["language"], "en")
        texte.sprache_festlegen("de")
        neu = self._neues_fenster()
        self.assertEqual(neu.sprachwahl.currentData(), "en")
        self.assertEqual(neu.tabs.tabText(0), "Overview")
        self.assertEqual(neu.freq_range_box.currentData(), bereich)
        self.assertEqual(neu.ppm_spin.value(), -12)

    def test_verschlüsselungswarnung_bleibt_beim_wechsel_wirksam(self):
        fenster = self._neues_fenster()
        fenster._encrypted_signal()
        protokoll = fenster.log.toPlainText()
        self.assertTrue(fenster._encrypted_notice_shown)
        self.assertIn("verschlüsselt", fenster.audio_status_label.text())
        self._sprache_wechseln(fenster, "en")
        self.assertIn("encrypted", fenster.audio_status_label.text().lower())
        self.assertIn("encrypt", fenster.audio_status_label.toolTip().lower())
        self.assertTrue(fenster._encrypted_notice_shown)
        self.assertEqual(fenster.log.toPlainText(), protokoll)
        fenster._encrypted_signal()
        self.assertEqual(fenster.log.toPlainText(), protokoll)
        self._sprache_wechseln(fenster, "de")
        self.assertIn("verschlüsselt", fenster.audio_status_label.text())

    def test_bestätigte_kandidaten_behalten_status_frequenz_und_zählung(self):
        fenster = self._neues_fenster()
        fenster._upsert_overview_candidate({
            "frequency_hz": 395625000, "probe_frequency_hz": 395626000,
            "xlate_hz": -1000, "iq_mode": "normal", "power": -27.5,
            "status": "bestätigt", "audio": "verschlüsselt",
        })
        fenster.overview_channel_table.selectRow(0)
        for sprache, status in (("en", "confirmed"), ("de", "bestätigt"), ("en", "confirmed")):
            with self.subTest(sprache=sprache):
                self._sprache_wechseln(fenster, sprache)
                self.assertEqual(fenster.overview_channel_table.rowCount(), 1)
                self.assertEqual(fenster.overview_channel_table.item(0, 1).text(), status)
                self.assertEqual(fenster.dashboard_tetra_value.text(), f"1 {status}")
                kandidat = fenster._selected_signal_candidate()
                self.assertIsNotNone(kandidat)
                self.assertEqual(kandidat["frequency"], 395625000)
                self.assertEqual(kandidat["probe_frequency"], 395626000)
                self.assertEqual(kandidat["xlate_hz"], -1000)
                self.assertEqual(kandidat["status"], "bestätigt")

    def test_kalibrierungsabschluss_nach_sprachwechsel(self):
        fenster = self._neues_fenster()
        # Der normale Startpfad setzt den Status; der Worker bleibt ohne Hardwarestart.
        with mock.patch.object(self.gui.CalibrationWorker, "start", return_value=None):
            fenster.start_calibration("ppm")
        self.assertEqual(fenster.calibration_status_label.text(), "Kalibrierung läuft...")
        self._sprache_wechseln(fenster, "en")
        self.assertNotIn("Kalibrierung", fenster.calibration_status_label.text())
        fenster._calibration_finished()
        self.assertIn("finished", fenster.calibration_status_label.text().lower())
        self.assertNotIn("running", fenster.calibration_status_label.text().lower())
        self._sprache_wechseln(fenster, "de")
        self.assertEqual(fenster.calibration_status_label.text(), "Kalibrierung beendet.")

    def test_audiohinweise_aktualisieren_englischen_status(self):
        fenster = self._neues_fenster()
        self._sprache_wechseln(fenster, "en")
        fenster._append_tetra("Audioausgabe: TETRA-Audio-Backend fehlt.")
        self.assertIn("missing", fenster.audio_status_label.text().lower())
        self.assertNotIn("fehlt", fenster.dashboard_audio_value.text())
        fenster._append_tetra("Audiohinweis: TETRA-Sprache ist verschlüsselt; Audioausgabe bleibt aus.")
        self.assertIn("encrypted", fenster.audio_status_label.text().lower())
        self.assertIn("encrypted", fenster.dashboard_audio_value.text().lower())

    def test_gui_cli_sprache_hat_vorrang_vor_gespeicherter_wahl(self):
        with mock.patch.object(sys, "argv", ["sprachtests", "--language", "en"]):
            fenster = self._neues_fenster()
        self.assertEqual(fenster.sprachwahl.currentData(), "en")
        self.assertEqual(fenster.tabs.tabText(0), "Overview")

    def test_automatische_formularbeschriftungen_wechseln_in_beide_sprachen(self):
        fenster = self._neues_fenster()

        def beschriftung_für(widget):
            # Keine Label-Wrapper vor dem Wechsel festhalten: Das würde einen
            # Fehler bei der Lebensdauer automatisch erzeugter Qt-Labels verdecken.
            for formular in fenster.findChildren(self.gui.QtWidgets.QFormLayout):
                for zeile in range(formular.rowCount()):
                    feld = formular.itemAt(zeile, self.gui.QtWidgets.QFormLayout.FieldRole)
                    if feld is None:
                        continue
                    if feld.widget() is widget:
                        return formular.labelForField(widget).text()
                    if feld.layout() is not None and feld.layout().indexOf(widget) >= 0:
                        return formular.labelForField(feld.layout()).text()
            self.fail("Für das Einstellungsfeld wurde keine Formularbeschriftung gefunden.")

        beschriftungen = (
            (fenster.device_box, "Gerät:", "Device:"),
            (fenster.ppm_spin, "PPM:", "PPM:"),
            (fenster.ref_freq_spin, "Referenzfrequenz:", "Reference frequency:"),
            (fenster.cal_span_spin, "Suchbreite ±:", "Search span ±:"),
            (fenster.theme_combo, "Design:", "Theme:"),
            (fenster.sprachwahl, "Sprache:", "Language:"),
        )
        for sprache in ("en", "de", "en"):
            self._sprache_wechseln(fenster, sprache)
            for widget, deutsch, englisch in beschriftungen:
                with self.subTest(sprache=sprache, beschriftung=deutsch):
                    self.assertEqual(beschriftung_für(widget), englisch if sprache == "en" else deutsch)

    def test_decoder_rohdaten_bleiben_trotz_treffendem_übersetzungstext_unverändert(self):
        fenster = self._neues_fenster()
        fenster.log_decoder_lines_cb.setChecked(True)
        self._sprache_wechseln(fenster, "en")
        fenster._append_tetra("Fehler")
        self.assertEqual(fenster.tetra_output.toPlainText(), "Fehler")
        self.assertEqual(fenster.decoder_data_table.item(0, 3).text(), "Fehler")
        self._sprache_wechseln(fenster, "de")
        self._sprache_wechseln(fenster, "en")
        self.assertEqual(fenster.tetra_output.toPlainText(), "Fehler")
        self.assertEqual(fenster.decoder_data_table.item(0, 3).text(), "Fehler")

    def test_tooltip_gekürzter_rohdaten_wird_nicht_übersetzt(self):
        fenster = self._neues_fenster()
        self._sprache_wechseln(fenster, "en")
        rohtext = "Prüfung fehlgeschlagen: Bitte unverändert lassen ÄÖÜß"
        eintrag = fenster._tabellen_item(rohtext, limit=12, übersetzbar=False)
        fenster.decoder_data_table.setRowCount(1)
        fenster.decoder_data_table.setItem(0, 3, eintrag)
        for sprache in ("en", "de", "en"):
            self._sprache_wechseln(fenster, sprache)
            self.assertLessEqual(len(eintrag.text()), 12)
            self.assertTrue(eintrag.text().startswith("Prüfung"))
            self.assertEqual(eintrag.toolTip(), rohtext)


if __name__ == "__main__":
    unittest.main()

# © 2026 Erik Schauer, do1ffe@darc.de
