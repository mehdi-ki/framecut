"""Interaction and regression tests for the thirty Smooth Workflow improvements."""
import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QPoint, QPointF, QMimeData, QUrl
from PySide6.QtGui import QImage, QDragEnterEvent, QDragMoveEvent, QDropEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from app import Editor, ExportDialog, MixerDialog
from core import Clip, import_clip, load_project, save_project, render, probe
from timeline import ASSET_MIME
from ux import error_guidance, load_preferences, line_icon, without_visual_effects
import test_core


class SmoothWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env=patch.dict(os.environ,{'FRAMECUT_DISABLE_UPDATE_CHECK':'1','QT_QPA_PLATFORM':'offscreen'})
        cls.env.start(); cls.app=QApplication.instance() or QApplication([])
        test_core.EditorCoreTest.setUpClass()

    @classmethod
    def tearDownClass(cls):
        test_core.EditorCoreTest.tearDownClass(); cls.env.stop()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.w=Editor(self.root,recovery=False); self.w.show(); QTest.qWait(40)
        self.w.live_preview_box.setChecked(False)
        self.errors=[]; self.w.error=lambda value:self.errors.append(str(value))

    def tearDown(self):
        w=self.w
        for job,_ in w.independent_jobs.values(): job.cancel.set()
        if w.worker: w.worker.cancel.set()
        self.wait_jobs()
        w.dirty=False; w.render_queue.clear()
        for child in w.findChildren(QMessageBox): child.close()
        w.close(); QTest.qWait(30); self.temp.cleanup()

    def wait_jobs(self):
        for _ in range(800):
            QTest.qWait(25)
            w=self.w
            if not w.independent_jobs and w.worker is None and w.visual_job is None and w.preview_worker is None and w.compare_job is None:
                return
        self.fail('Background work did not finish in 20 seconds')

    def add_video(self,position=0,track=1,end=3):
        w=self.w; asset=import_clip(test_core.EditorCoreTest.blue)
        w.assets.append(asset); clip=replace(asset,position=position,track=track,end=end)
        w.clips.append(clip); w.refresh_media(); w.set_selection([clip.uid],clip.uid); w.refresh()
        return clip

    def test_workspace_roundtrip_and_corrupt_preferences(self):
        w=self.w; self.add_video(); w.toggle_asset_favorite()
        w.edit_mode_combo.setCurrentIndex(1); w.media_view_combo.setCurrentIndex(1)
        w.zoom_slider.setValue(95); w.reduced_motion.setChecked(True); w.set_ui_scale(115)
        w.inspector_sections[0]['toggle'].setChecked(False); w.save_workspace()
        stored=load_preferences(w.preferences_path)
        self.assertEqual(stored['zoom'],95); self.assertEqual(stored['ui_scale'],115)
        self.assertIn(str(test_core.EditorCoreTest.blue.resolve()),stored['favorites'])
        other=Editor(self.root,recovery=False); other.show(); QTest.qWait(40)
        self.assertEqual(other.edit_mode_combo.currentData(),'pro')
        self.assertEqual(other.zoom_slider.value(),95); self.assertTrue(other.reduced_motion.isChecked())
        self.assertFalse(other.inspector_sections[0]['toggle'].isChecked()); other.close()
        broken=self.root/'broken.json'; broken.write_text('{')
        self.assertEqual(load_preferences(broken),{})

    def test_zoom_stays_under_pointer_and_selection_survives(self):
        w=self.w; clip=self.add_video(position=70)
        bar=w.scroll.horizontalScrollBar(); QTest.qWait(30); bar.setValue(1200)
        x=bar.value()+310; time_before=w.timeline.time_at(x)
        w.zoom_at_pointer(1,x)
        time_after=w.timeline.time_at(bar.value()+310)
        self.assertAlmostEqual(time_before,time_after,delta=1/w.timeline.scale)
        self.assertEqual(w.current,clip.uid)

    def test_larger_trim_hit_area_and_locked_track(self):
        w=self.w; clip=self.add_video(); r=w.timeline.rect_for(clip)
        point=QPointF(r.right()+4,r.center().y())
        self.assertEqual(w.timeline.hit(point).uid,clip.uid)
        self.assertEqual(w.timeline.edge_mode(clip,point),'right')
        w.toggle_track_lock(clip.track); count=len(w.history)
        QTest.mousePress(w.timeline,Qt.LeftButton,Qt.NoModifier,point.toPoint())
        QTest.mouseMove(w.timeline,point.toPoint()-QPoint(30,0)); QTest.mouseRelease(w.timeline,Qt.LeftButton)
        self.assertEqual(len(w.history),count)

    def test_noop_properties_and_one_gesture_one_history_entry(self):
        w=self.w; clip=self.add_video(); w.apply_properties(); baseline=len(w.history)
        w.apply_properties(); self.assertEqual(len(w.history),baseline)
        w.timeline.snap=False; r=w.timeline.rect_for(clip); start=r.center().toPoint()
        QTest.mousePress(w.timeline,Qt.LeftButton,Qt.NoModifier,start)
        for step in (10,20,30,40,50): QTest.mouseMove(w.timeline,start+QPoint(step,0),5)
        QTest.mouseRelease(w.timeline,Qt.LeftButton,Qt.NoModifier,start+QPoint(50,0))
        self.assertEqual(len(w.history),baseline+1)
        w.undo(); self.assertAlmostEqual(w.current_clip().position,0)

    def test_typing_and_local_undo_never_trigger_edit_shortcuts(self):
        w=self.w; clip=self.add_video(); w.inline_name.setFocus(); w.inline_name.selectAll()
        QTest.keyClicks(w.inline_name,'s qwi jkl text'); QTest.keyClick(w.inline_name,Qt.Key_Space)
        self.assertEqual(len(w.clips),1); self.assertEqual(len(w.history),0)
        QTest.keyClick(w.inline_name,Qt.Key_Backspace); QTest.keyClick(w.inline_name,Qt.Key_Z,Qt.ControlModifier)
        self.assertEqual(len(w.clips),1); self.assertEqual(w.current,clip.uid)
        self.assertFalse(w.transport_timer.isActive())

    def test_escape_discards_trim_and_restores_playhead_grip(self):
        w=self.w; clip=self.add_video(); w.timeline.snap=False; r=w.timeline.rect_for(clip)
        edge=QPoint(round(r.right()-2),round(r.center().y()))
        QTest.mousePress(w.timeline,Qt.LeftButton,Qt.NoModifier,edge)
        QTest.mouseMove(w.timeline,edge-QPoint(40,0),5); self.assertTrue(w.timeline.ghost)
        QTest.keyClick(w.timeline,Qt.Key_Escape)
        QTest.mouseRelease(w.timeline,Qt.LeftButton,Qt.NoModifier,edge-QPoint(40,0))
        self.assertEqual(w.current_clip(),clip); self.assertFalse(w.history)
        w.set_playhead(.5); grip=QPoint(w.timeline.LEFT+30,30)
        QTest.mousePress(w.timeline,Qt.LeftButton,Qt.NoModifier,grip)
        QTest.mouseMove(w.timeline,grip+QPoint(60,0),5)
        QTest.keyClick(w.timeline,Qt.Key_Escape); QTest.mouseRelease(w.timeline,Qt.LeftButton)
        self.assertAlmostEqual(w.playhead,.5)

    def test_audio_fade_handles_commit_and_undo(self):
        w=self.w; clip=import_clip(test_core.EditorCoreTest.tone); w.clips=[clip]; w.assets=[clip]
        w.set_selection([clip.uid],clip.uid); w.refresh(); r=w.timeline.rect_for(clip)
        start=QPoint(round(r.left()+8),round(r.top()+10))
        QTest.mousePress(w.timeline,Qt.LeftButton,Qt.NoModifier,start)
        QTest.mouseMove(w.timeline,start+QPoint(30,0),5)
        QTest.mouseRelease(w.timeline,Qt.LeftButton,Qt.NoModifier,start+QPoint(30,0))
        self.assertAlmostEqual(w.current_clip().fade_in,.5)
        self.assertEqual(len(w.history),1); w.undo(); self.assertEqual(w.current_clip().fade_in,0)

    def test_drop_target_preview_rejects_overlap(self):
        w=self.w; self.add_video(); mime=QMimeData(); mime.setData(ASSET_MIME,b'0')
        point=QPoint(w.timeline.LEFT+30,w.timeline.TOP+w.timeline.ROW+24)
        enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        QApplication.sendEvent(w.timeline,enter)
        move=QDragMoveEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        QApplication.sendEvent(w.timeline,move)
        self.assertIsNotNone(w.timeline.drop_preview); self.assertFalse(w.timeline.ghost_valid)
        drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
        QApplication.sendEvent(w.timeline,drop); self.assertFalse(drop.isAccepted()); self.assertEqual(len(w.clips),1)

    def test_middle_pan_and_follow_suspension(self):
        w=self.w; self.add_video(position=50); QTest.qWait(30)
        bar=w.scroll.horizontalScrollBar(); bar.setValue(300)
        start=QPoint(bar.value()+250,w.timeline.TOP+50)
        QTest.mousePress(w.timeline,Qt.MiddleButton,Qt.NoModifier,start)
        QTest.mouseMove(w.timeline,start-QPoint(60,0),10)
        QTest.mouseRelease(w.timeline,Qt.MiddleButton,Qt.NoModifier,start-QPoint(60,0))
        self.assertGreater(bar.value(),300); self.assertTrue(w.follow_suspended)
        before=bar.value(); w.playhead=52; w.follow_playhead(); self.assertEqual(bar.value(),before)
        w.follow_suspended=False; w.follow_playhead(); self.assertGreater(bar.value(),before)

    def test_inline_metadata_visibility_and_project_roundtrip(self):
        w=self.w; self.add_video(); w.inline_name.setText('Intro'); w.inline_enabled.setChecked(False)
        w.inline_volume.setValue(40); w.inline_apply(color='#72d0ac')
        clip=w.current_clip(); self.assertEqual(clip.display_name,'Intro'); self.assertFalse(clip.enabled)
        project=self.root/'test.framecut'; save_project(project,w.clips,w.preset.currentText(),w.tracks)
        loaded=load_project(project)['clips'][0]; self.assertEqual(loaded,clip)
        target=self.root/'disabled.mp4'; render([replace(clip,end=.3)],w.tracks,target,(160,90))
        self.assertGreater(probe(target)[0],.25)
        raw=test_core.ff('-i',target,'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1').stdout
        self.assertLess(max(raw),10)

    def test_visual_history_can_move_back_and_forward(self):
        w=self.w; clip=self.add_video()
        w.commit_drag(replace(clip,position=1)); w.commit_drag(replace(w.current_clip(),position=2))
        w.show_history(); self.assertEqual(w.history_list.count(),3)
        w.jump_history(0); self.assertAlmostEqual(w.current_clip().position,0)
        w.jump_history(2); self.assertAlmostEqual(w.current_clip().position,2)
        w.remove(); self.assertEqual(len(w.clips),0); w.undo(); self.assertEqual(len(w.clips),1)

    def test_export_is_nonblocking_and_uses_frozen_snapshot(self):
        w=self.w; clip=self.add_video(end=.3); clips=w.snapshot()[0]
        gate=threading.Event(); started=threading.Event(); observed=[]
        def rendering(clips,*args,**kwargs):
            started.set(); gate.wait(3); observed.append(clips[0].position)
        w.render_queue.append({'target':self.root/'out.mp4','clips':clips,'tracks':list(w.tracks),
            'track_states':{},'size':(160,90),'settings':{},'label':'Testexport'})
        with patch('app.render',side_effect=rendering):
            try:
                w.process_render_queue()
                for _ in range(80):
                    QTest.qWait(5)
                    if started.is_set(): break
                self.assertTrue(started.is_set()); self.assertTrue(w.centralWidget().isEnabled())
                self.assertIsNone(w.worker); w.commit_drag(replace(clip,position=2))
                self.assertAlmostEqual(w.current_clip().position,2)
            finally: gate.set(); self.wait_jobs()
        self.assertEqual(observed,[0])

    def test_import_metadata_and_proxy_work_in_background(self):
        w=self.w; w.import_paths([str(test_core.EditorCoreTest.red)])
        self.assertIn('import',w.independent_jobs); self.assertIsNone(w.worker)
        self.wait_jobs(); self.assertEqual(len(w.assets),1); self.assertIn(w.assets[0].path,w.thumbnails)
        w.drop_asset(0,0,1); original=w.current_clip().path
        w.performance_combo.setCurrentIndex(w.performance_combo.findData('smooth'))
        self.wait_jobs(); self.assertTrue(w.proxy_map); self.assertEqual(w.current_clip().path,original)
        self.assertTrue(w.quick_preview_box.isChecked()); self.assertFalse(self.errors)

    def test_autosave_generations_and_corrupt_primary_recovery(self):
        w=self.w; clip=self.add_video(); w.recovery_enabled=True
        w.changed(); w.autosave(); w.commit_drag(replace(clip,position=1)); w.autosave()
        previous=self.root/'recovery-previous.framecut'; self.assertTrue(previous.is_file())
        self.assertIn('Wiederherstellbar',w.autosave_pill.text())
        w.recovery_path.write_text('{broken')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes): w.offer_recovery()
        self.assertEqual(w.current_clip().position,0); self.assertTrue(list(self.root.glob('recovery-unreadable-*.framecut')))

    def test_compare_restores_original_source_and_keeps_project_unchanged(self):
        w=self.w; clip=self.add_video(end=.35)
        w.clips=[replace(clip,brightness=.3)]; w.refresh(); before=w.snapshot()
        w.compare_pressed(); self.assertTrue(w.compare_active); self.wait_jobs()
        self.assertIn('OHNE BILD-EFFEKTE',w.preview_status.text())
        w.compare_released(); self.assertFalse(w.compare_active); self.assertEqual(w.snapshot(),before)
        stripped=without_visual_effects(w.clips[0]); self.assertEqual(stripped.brightness,0)
        self.assertEqual(stripped.position,clip.position)

    def test_preview_alignment_commit_and_escape(self):
        w=self.w; clip=self.add_video(); w.clips=[replace(clip,video_scale=.5)]
        w.video.frame=QImage(320,180,QImage.Format_RGB32); w.video.frame.fill(Qt.blue)
        w.video_stack.setCurrentIndex(1); w.refresh(); QTest.qWait(30)
        start=w.video.object_rect().center().toPoint()
        QTest.mousePress(w.video,Qt.LeftButton,Qt.NoModifier,start)
        QTest.mouseMove(w.video,start+QPoint(40,0),10); QTest.mouseRelease(w.video,Qt.LeftButton,Qt.NoModifier,start+QPoint(40,0))
        self.assertGreater(w.current_clip().video_x,.5); self.assertEqual(len(w.history),1)
        w.undo(); self.assertAlmostEqual(w.current_clip().video_x,.5)
        w.video_stack.setCurrentIndex(1); start=w.video.object_rect().center().toPoint()
        QTest.mousePress(w.video,Qt.LeftButton,Qt.NoModifier,start); QTest.mouseMove(w.video,start+QPoint(30,0),10)
        QTest.keyClick(w.video,Qt.Key_Escape); QTest.mouseRelease(w.video,Qt.LeftButton)
        self.assertAlmostEqual(w.current_clip().video_x,.5)

    def test_late_preview_does_not_replace_comparison(self):
        from unittest.mock import Mock
        w=self.w; self.add_video(); job=Mock(); w.preview_worker=job
        w.compare_active=True; w._compare_saved=(QUrl(),0,'timeline',False)
        target=str(test_core.EditorCoreTest.blue)
        with patch.object(w,'load_player') as load:
            w.finish_preview_job(job,{'ok':True,'value':(target,w.revision)},True,w.revision,w.preview_signature_for_current())
            load.assert_not_called(); self.assertEqual(w.preview_path,target)
            w.compare_released(); load.assert_called_once()
            self.assertEqual(load.call_args.args[0],target)

    def test_mixer_keeps_tracks_independent_and_groups_each_drag(self):
        w=self.w; self.add_video(); mixer=MixerDialog(w)
        tracks=list(mixer.track_controls); first,last=tracks[0],tracks[-1]
        slider=mixer.track_controls[first]['volume_slider']
        slider.sliderPressed.emit(); slider.setValue(80); slider.setValue(70); slider.sliderReleased.emit()
        self.assertEqual(len(w.history),1)
        self.assertEqual(w.track_states[first]['volume'],.7)
        self.assertEqual(mixer.track_controls[last]['volume_spin'].value(),100)
        slider.sliderPressed.emit(); slider.setValue(60); slider.sliderReleased.emit()
        self.assertEqual(len(w.history),2); w.undo()
        self.assertEqual(w.track_states[first]['volume'],.7); mixer.close()

    def test_trim_preview_decodes_real_source_frame(self):
        w=self.w; clip=self.add_video(); w.show_trim_preview(replace(clip,end=2),'right')
        for _ in range(150):
            QTest.qWait(20)
            if not w.trim_hint.pixmap().isNull(): break
        self.assertFalse(w.trim_hint.pixmap().isNull())
        color=w.trim_hint.pixmap().toImage().pixelColor(20,20); self.assertGreater(color.blue(),180)
        self.assertIn('-1.000',w.statusBar().currentMessage())
        w.hide_trim_preview(); self.assertTrue(w.trim_hint.isHidden())

    def test_export_uses_source_fps_and_explains_output(self):
        w=self.w; self.add_video(); dialog=ExportDialog(w)
        self.assertEqual(dialog.fps.value(),30); self.assertTrue(dialog.advanced_panel.isHidden())
        self.assertIn('1920 × 1080',dialog.summary.text())
        dialog.advanced_toggle.setChecked(True); self.assertFalse(dialog.advanced_panel.isHidden())
        dialog.fps.setValue(60); self.assertIn('60 FPS',dialog.summary.text()); dialog.close()
        self.assertEqual(import_clip(test_core.EditorCoreTest.red).source_fps,24)

    def test_no_scroll_jump_and_disabled_reasons(self):
        w=self.w; self.add_video(); w.edit_mode_combo.setCurrentIndex(1)
        for entry in w.inspector_sections: entry['toggle'].setChecked(True)
        QTest.qWait(40); scroll=w.inspector_scroll.verticalScrollBar(); scroll.setValue(450)
        original=scroll.value(); w.fill_inspector(); self.assertEqual(scroll.value(),original)
        w.toggle_track_lock(1); self.assertIn('Entsperre',w.volume.property('disabledReason'))

    def test_numeric_fine_step_reset_and_escape(self):
        w=self.w; clip=import_clip(test_core.EditorCoreTest.tone); w.clips=[clip]; w.assets=[clip]
        w.set_selection([clip.uid],clip.uid); w.refresh()
        spin=w.inline_volume; spin.setFocus(); spin.setValue(70)
        QTest.keyPress(spin,Qt.Key_Shift); spin.stepBy(1); QTest.keyRelease(spin,Qt.Key_Shift)
        self.assertAlmostEqual(spin.value(),70.1)
        QTest.mouseDClick(spin,Qt.LeftButton,Qt.NoModifier,QPoint(spin.width()-10,spin.height()//2))
        self.assertEqual(spin.value(),100)

    def test_removing_selects_neighbor_and_cut_navigation(self):
        w=self.w; first=self.add_video(); second=self.add_video(position=3)
        w.remove(); self.assertEqual(w.current,first.uid)
        w.undo(); self.assertEqual(w.current,second.uid)
        w.set_playhead(.2); w.jump_cut(1); self.assertEqual(w.playhead,3)
        w.jump_cut(-1); self.assertEqual(w.playhead,0)

    def test_project_status_error_actions_and_icon_family(self):
        w=self.w; w.show_project_status(); self.assertIsNone(QApplication.activeModalWidget())
        title,hint,action=error_guidance('Permission denied: output.mp4'); self.assertEqual(action,'export')
        self.assertIn('beschreibbar',title)
        for name in ('edit-delete','edit-cut','document-save','snap-to-grid','document-export'):
            self.assertFalse(line_icon(name).isNull())
        w.set_ui_scale(150); self.assertIn('font-size: 18px',w.styleSheet())

    def test_stale_import_result_does_not_modify_new_project(self):
        w=self.w; gate=threading.Event(); callbacks=[]
        try:
            w.start_independent_job('import','Test',lambda p,c:gate.wait(2),lambda result:callbacks.append(result))
            w.new_project(); gate.set(); self.wait_jobs()
        finally: gate.set()
        self.assertFalse(callbacks); self.assertFalse(w.clips)


if __name__=='__main__': unittest.main()
