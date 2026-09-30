"""Run using QT_QPA_PLATFORM=offscreen python3 -m unittest -v test_gui."""
import tempfile
import os
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtCore import Qt,QPoint,QMimeData,QPointF
from PySide6.QtGui import QDragEnterEvent,QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox,QInputDialog,QFileDialog
from app import Editor,ExportDialog,STYLE
from core import load_project,length,parse_subtitle_file,save_project
from timeline import ASSET_MIME
import test_core


class GuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion');cls.app.setStyleSheet(STYLE)
        test_core.EditorCoreTest.setUpClass()

    @classmethod
    def tearDownClass(cls):test_core.EditorCoreTest.tearDownClass()

    def wait_job(self,w):
        # Complex animated video effects can take a little longer on the
        # software-only CI preview path than a plain timeline render.
        for _ in range(500):
            QTest.qWait(40)
            if w.worker is None and w.preview_worker is None:return
        self.fail('Background job did not finish after 20 seconds')

    def test_framecut_file_association_loads_project_argument(self):
        with tempfile.TemporaryDirectory() as state:
            project=Path(state)/'associated.framecut'
            save_project(project,[], '720p · 16:9',[2,1,-1,-2])
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            self.assertTrue(w.open_project_path(str(project)))
            self.assertEqual(Path(w.project_path),project.resolve())
            self.assertEqual(w.clips,[])
            w.close();QTest.qWait(50)

    def test_timeline_workflow_and_recovery(self):
        with tempfile.TemporaryDirectory() as state:
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.blue),str(test_core.EditorCoreTest.red),str(test_core.EditorCoreTest.tone)])
            self.wait_job(w);self.assertFalse(errors);self.assertEqual(len(w.assets),3)
            w.drop_asset(0,0,1);w.drop_asset(1,.5,2);w.drop_asset(2,0,-1)
            self.assertEqual(len(w.clips),3)
            w.toggle_track_mute(-1);self.assertTrue(w.track_states[-1]['muted'])
            w.toggle_track_mute(-1);self.assertFalse(w.track_states[-1]['muted'])
            w.select_clip(w.clips[0].uid);before_position=w.current_clip().position
            w.toggle_track_lock(1);self.assertTrue(w.track_states[1]['locked'])
            w.commit_drag(replace(w.current_clip(),position=before_position+1))
            self.assertAlmostEqual(w.current_clip().position,before_position)
            w.toggle_track_lock(1);self.assertFalse(w.track_states[1]['locked'])
            w.select_clip(w.clips[0].uid)
            w.keyframe_time.setValue(.25);w.transform_scale.setValue(1.35);w.transform_x.setValue(25);w.rotation.setValue(12)
            w.set_keyframe();self.assertEqual(len(w.current_clip().keyframes),1)
            w.keyframe_list.setCurrentRow(0);self.assertAlmostEqual(w.transform_scale.value(),1.35,places=2)
            w.brightness.setValue(.12);w.contrast.setValue(1.25);w.saturation.setValue(.65);w.apply_properties()
            self.assertAlmostEqual(w.current_clip().brightness,.12,places=2)
            self.assertAlmostEqual(w.current_clip().contrast,1.25,places=2)
            self.assertAlmostEqual(w.current_clip().saturation,.65,places=2)
            w.opacity.setValue(62);w.blur.setValue(1.5);w.sharpen.setValue(.8);w.apply_properties()
            self.assertAlmostEqual(w.current_clip().opacity,.62,places=2)
            self.assertAlmostEqual(w.current_clip().blur,1.5,places=1)
            self.assertAlmostEqual(w.current_clip().sharpen,.8,places=1)
            w.keyframe_time.setValue(.5);w.opacity.setValue(35);w.blur.setValue(2.5);w.set_keyframe()
            effect_frame=min(w.current_clip().keyframes,key=lambda value:abs(float(value['time'])-.5))
            self.assertAlmostEqual(effect_frame['opacity'],.35,places=2)
            self.assertAlmostEqual(effect_frame['blur'],2.5,places=1)
            w.select_clip(w.clips[2].uid);w.volume_keyframe_time.setValue(.25);w.volume.setValue(35);w.set_volume_keyframe()
            self.assertEqual(len(w.current_clip().volume_keyframes),1)
            w.volume_keyframe_list.setCurrentRow(0);self.assertAlmostEqual(w.volume.value(),35,places=1)
            # Test actual drag events with a track change and snapping disabled.
            w.timeline.snap=False;clip=w.clips[0]
            start=w.timeline.rect_for(clip).center().toPoint()
            delta=QPoint(60,-70)
            QTest.mousePress(w.timeline,Qt.LeftButton,Qt.NoModifier,start)
            QTest.mouseMove(w.timeline,start+QPoint(60,0),20)
            QTest.mouseRelease(w.timeline,Qt.LeftButton,Qt.NoModifier,start+QPoint(60,0))
            self.assertAlmostEqual(w.clips[0].position,1,places=3)
            self.assertTrue(w.history)
            w.undo();self.assertEqual(w.clips[0].position,0)
            w.redo();self.assertEqual(w.clips[0].position,1)
            w.undo()
            # Move the base clip to a free place on the upper video track.
            start=w.timeline.rect_for(w.clips[0]).center().toPoint()
            QTest.mousePress(w.timeline,Qt.LeftButton,Qt.NoModifier,start)
            QTest.mouseMove(w.timeline,start+QPoint(120,-70),20)
            QTest.mouseRelease(w.timeline,Qt.LeftButton,Qt.NoModifier,start+QPoint(120,-70))
            self.assertEqual(w.clips[0].track,2);self.assertAlmostEqual(w.clips[0].position,2)
            w.undo();self.assertEqual(w.clips[0].track,1)
            # Native Qt media-drop events target a specific audio track/time.
            mime=QMimeData();mime.setData(ASSET_MIME,b'2')
            point=QPoint(w.timeline.LEFT+240,w.timeline.TOP+3*w.timeline.ROW+20)
            enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
            QApplication.sendEvent(w.timeline,enter);self.assertTrue(enter.isAccepted())
            drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
            QApplication.sendEvent(w.timeline,drop)
            self.assertEqual(len(w.clips),4);self.assertEqual(w.clips[-1].track,-2)
            self.assertAlmostEqual(w.clips[-1].position,4);w.undo()
            # Right-edge trim driven by mouse events.
            c=w.clips[0];rect=w.timeline.rect_for(c);edge=QPoint(round(rect.right()-2),round(rect.center().y()))
            QTest.mousePress(w.timeline,Qt.LeftButton,Qt.NoModifier,edge)
            QTest.mouseMove(w.timeline,edge-QPoint(60,0),20)
            QTest.mouseRelease(w.timeline,Qt.LeftButton,Qt.NoModifier,edge-QPoint(60,0))
            self.assertAlmostEqual(w.clips[0].end,2,places=3)
            w.select_clip(w.clips[1].uid);w.detach_audio()
            self.assertEqual(len(w.clips),4);self.assertEqual(w.clips[1].volume,0)
            # Music source preserves its input trim and independent position.
            w.select_clip(w.clips[2].uid);w.position.setValue(.25);w.start.setValue(.1);w.end.setValue(1.5);w.apply_properties()
            self.assertFalse(errors);self.assertAlmostEqual(w.clips[2].position,.25)
            # Global timeline split and undo.
            w.select_clip(w.clips[0].uid);w.set_playhead(.8);w.split();self.assertEqual(len(w.clips),5)
            w.undo();self.assertEqual(len(w.clips),4)
            w.recovery_enabled=True;w.autosave();recovered=load_project(w.recovery_path)
            self.assertEqual(recovered['clips'],w.clips);self.assertEqual(len(recovered['assets']),3)
            # Prepared preview must decode real frames and use all tracks.
            frames=[];w.video.videoSink().videoFrameChanged.connect(lambda f:frames.append(f.isValid()))
            w.set_playhead(0);w.toggle_play();self.wait_job(w);QTest.qWait(500)
            self.assertEqual(w.preview_revision,w.revision);self.assertTrue(Path(w.preview_path).is_file())
            self.assertIn(True,frames);self.assertGreater(w.player.position(),0)
            self.assertFalse(w.video.frame.isNull())
            w.player.pause()
            if os.environ.get('FRAMECUT_TEST_SCREENSHOT'):
                w.grab().save(os.environ['FRAMECUT_TEST_SCREENSHOT'])
            # Switching selected source must not map old source time onto another clip.
            w.select_clip(w.clips[0].uid);w.source_preview();QTest.qWait(150)
            w.select_clip(w.clips[2].uid);self.assertEqual(w.mode,'timeline')
            # Unmodified click should not create a new history entry.
            before=len(w.history);r=w.timeline.rect_for(w.clips[0]);QTest.mouseClick(w.timeline,Qt.LeftButton,Qt.NoModifier,r.center().toPoint())
            self.assertEqual(len(w.history),before)
            # Selecting a clip must not move the independent playhead.
            w.set_playhead(.35);before_playhead=w.playhead
            QTest.mouseClick(w.timeline,Qt.LeftButton,Qt.NoModifier,r.center().toPoint())
            self.assertAlmostEqual(w.playhead,before_playhead,places=3)
            self.assertFalse(errors)
            # Simulate a lost session: keep recovery data, then invoke real recovery flow.
            w.autosave();expected=[replace(c) for c in w.clips]
            w.recovery_enabled=False;w.dirty=False;w.close();QTest.qWait(50)
            restored=Editor(state,recovery=False);restored.recovery_enabled=True
            with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):restored.offer_recovery()
            self.assertEqual(restored.clips,expected);self.assertTrue(restored.dirty)
            self.assertEqual(len(restored.assets),3)
            restored.dirty=False;restored.close();QTest.qWait(50)

    def test_multi_selection_clipboard_groups_ripple_and_track_management(self):
        with tempfile.TemporaryDirectory() as state:
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.blue),str(test_core.EditorCoreTest.red),str(test_core.EditorCoreTest.tone)])
            self.wait_job(w);self.assertFalse(errors)
            w.drop_asset(0,0,1);w.drop_asset(1,0,2);self.assertEqual(len(w.clips),2)
            original_ids=[w.clips[0].uid,w.clips[1].uid]
            w.set_selection(original_ids,original_ids[-1]);self.assertEqual(set(w.selection),set(original_ids))
            w.copy_selection();w.paste_selection(anchor=0);self.assertEqual(len(w.clips),4)
            pasted=list(w.selection);self.assertEqual(len(pasted),2)
            w.group_selection();self.assertTrue(all(clip.group_id for clip in w.selected_clips()))
            group_id=w.selected_clips()[0].group_id;self.assertTrue(all(clip.group_id==group_id for clip in w.selected_clips()))
            w.ungroup_selection();self.assertTrue(all(not clip.group_id for clip in w.selected_clips()))
            w.set_selection(pasted,pasted[-1]);w.ripple_delete();self.assertEqual(len(w.clips),2)
            original_base=w.clips[0].uid;w.select_clip(original_base);w.copy_selection();w.set_playhead(0);w.ripple_insert();self.assertEqual(len(w.clips),3)
            self.assertGreater(next(clip for clip in w.clips if clip.uid==original_base).position,0)
            w.remove();self.assertEqual(len(w.clips),2)
            w.select_clip(w.clips[0].uid);w.duplicate_selection();self.assertEqual(len(w.clips),3);w.remove();self.assertEqual(len(w.clips),2)
            with patch.object(QInputDialog,'getText',return_value=('Main Video',True)):
                w.rename_track(1)
            self.assertEqual(w.track_names[1],'Main Video')
            w.delete_track(-2);self.assertNotIn(-2,w.tracks)
            self.assertFalse(errors)
            w.dirty=False
            w.close();QTest.qWait(50)

    def test_step2_professional_timeline_controls(self):
        with tempfile.TemporaryDirectory() as state:
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.blue),str(test_core.EditorCoreTest.red)]);self.wait_job(w)
            w.drop_asset(0,0,1);w.drop_asset(1,4,1)
            w.set_playhead(1.0)
            with patch.object(QInputDialog,'getText',return_value=('Beat',True)):
                w.add_marker('marker')
            w.set_playhead(2.0)
            with patch.object(QInputDialog,'getText',return_value=('Kapitel zwei',True)):
                w.add_marker('chapter')
            self.assertEqual([marker['label'] for marker in w.markers],['Beat','Kapitel zwei'])
            self.assertEqual(len(w.timeline.markers),2)
            w.recovery_enabled=True;w.autosave();saved=load_project(w.recovery_path)
            self.assertEqual(saved['markers'],w.markers)
            self.assertIn(2.0,w.timeline.snap_targets());self.assertIn(length(w.clips),w.timeline.snap_targets())

            # Insert shifts later clips and global markers together.
            w.select_clip(w.clips[0].uid);w.copy_selection();w.set_playhead(0);w.insert_selection()
            self.assertEqual(len(w.clips),3);self.assertAlmostEqual(w.markers[0]['time'],4.0,places=3)

            # Overwrite trims the covered source without moving the rest of the timeline.
            w.dirty=False;w.new_project()
            w.import_paths([str(test_core.EditorCoreTest.blue),str(test_core.EditorCoreTest.red)]);self.wait_job(w)
            w.drop_asset(0,0,1)
            candidate=replace(w.assets[1],position=0,track=1,uid='overwrite-candidate')
            w.clipboard=[candidate];w.set_playhead(1);w.overwrite_selection()
            self.assertEqual(len(w.clips),3)
            self.assertEqual(sorted(round(clip.position,3) for clip in w.clips),[0,1,2])
            self.assertFalse(errors)

            # Empty-space marquee selects multiple clips; J/K/L controls are stateful.
            start=QPoint(w.timeline.LEFT+240,w.timeline.TOP+2)
            end=QPoint(w.timeline.LEFT+1,w.timeline.TOP+2*w.timeline.ROW+5)
            QTest.mousePress(w.timeline,Qt.LeftButton,Qt.NoModifier,start)
            QTest.mouseMove(w.timeline,end,20);QTest.mouseRelease(w.timeline,Qt.LeftButton,Qt.NoModifier,end)
            self.assertEqual(len(w.selection),3)
            with patch.object(w,'preview_is_current',return_value=True),patch.object(w,'load_player'):
                w.transport_l();self.assertEqual(w.transport_rate,1)
                w.transport_l();self.assertEqual(w.transport_rate,2)
                w.transport_j();self.assertEqual(w.transport_rate,-1)
                w.transport_k();self.assertEqual(w.transport_rate,0);self.assertFalse(w.transport_timer.isActive())
            self.assertFalse(errors)
            w.dirty=False;w.close();QTest.qWait(50)

    def test_subtitle_import_and_text_inspector(self):
        with tempfile.TemporaryDirectory() as state:
            subtitle=Path(state)/'captions.srt'
            subtitle.write_text('''1\n00:00:00,000 --> 00:00:00,900\nHello\n\n2\n00:00:01,100 --> 00:00:02,000\nWorld\n''',encoding='utf-8')
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.blue)]);self.wait_job(w)
            w.drop_asset(0,0,1)
            w.import_subtitles(str(subtitle));self.wait_job(w)
            self.assertFalse(errors);self.assertEqual(len([c for c in w.clips if c.kind=='text']),2)
            text_clip=next(c for c in w.clips if c.kind=='text');self.assertEqual(text_clip.text,'Hello')
            self.assertTrue(any(name.startswith('Untertitel') for name in w.track_names.values()))
            w.select_clip(text_clip.uid)
            w.text_bold.setChecked(True);w.text_italic.setChecked(True);w.text_outline_width.setValue(3);w.text_shadow_size.setValue(2)
            w.text_background_opacity.setValue(65);w.text_animation.setCurrentIndex(w.text_animation.findData('fade'));w.apply_properties()
            updated=w.current_clip();self.assertTrue(updated.font_bold and updated.font_italic)
            self.assertEqual(updated.outline_width,3);self.assertEqual(updated.shadow_size,2)
            self.assertEqual(updated.background_opacity,.65);self.assertEqual(updated.text_animation,'fade')
            self.assertFalse(errors)
            w.dirty=False;w.close();QTest.qWait(50)

    def test_step4_subtitle_export_and_native_style_preset(self):
        with tempfile.TemporaryDirectory() as state:
            subtitle=Path(state)/'captions.srt'
            subtitle.write_text('''1\n00:00:00,000 --> 00:00:00,900\nHello\n\n2\n00:00:01,100 --> 00:00:02,000\nWorld\n''',encoding='utf-8')
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.blue)]);self.wait_job(w)
            w.drop_asset(0,0,1);w.import_subtitles(str(subtitle));self.wait_job(w)
            text_clip=next(clip for clip in w.clips if clip.kind=='text')
            w.select_clip(text_clip.uid);w.text_style_preset.setCurrentIndex(w.text_style_preset.findData('subtitle'));w.apply_text_style_preset()
            styled=w.current_clip();self.assertEqual(styled.font_size,42);self.assertTrue(styled.background_enabled);self.assertAlmostEqual(styled.y,.86)
            self.assertTrue(w.subtitle_export_button.isEnabled())
            target=Path(state)/'roundtrip.vtt'
            with patch.object(QFileDialog,'getSaveFileName',return_value=(str(target),'WebVTT (*.vtt)')):
                w.export_subtitles()
            self.assertTrue(target.is_file());self.assertEqual([cue['text'] for cue in parse_subtitle_file(target)],['Hello','World'])
            self.assertFalse(errors)
            w.dirty=False;w.close();QTest.qWait(50)

    def test_step5_media_bin_search_filter_sort_and_filtered_drop(self):
        with tempfile.TemporaryDirectory() as state:
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.blue),str(test_core.EditorCoreTest.red),str(test_core.EditorCoreTest.tone)])
            self.wait_job(w);self.assertFalse(errors);self.assertEqual(w.media_list.count(),3)

            # Search and type filtering operate on the full asset list.
            w.media_search.setText('red portrait')
            self.assertEqual(w.media_list.count(),1)
            self.assertEqual(w.media_list.item(0).data(w.media_list.ASSET_INDEX_ROLE),1)
            w.media_search.clear();w.media_filter.setCurrentIndex(w.media_filter.findData('audio'))
            self.assertEqual(w.media_list.count(),1)
            self.assertEqual(w.media_list.item(0).data(w.media_list.ASSET_INDEX_ROLE),2)

            # Sorting/filtering must still add the correct source asset, not
            # whichever asset happens to occupy visual row zero.
            w.media_sort.setCurrentIndex(w.media_sort.findData('name'))
            w.add_selected_asset()
            self.assertEqual(len(w.clips),1);self.assertEqual(w.clips[0].path,str(test_core.EditorCoreTest.tone.resolve()))
            w.media_filter.setCurrentIndex(w.media_filter.findData('all'));w.media_search.setText('does-not-exist')
            self.assertEqual(w.media_list.count(),0);self.assertIn('0 / 3',w.media_count.text())
            self.assertFalse(errors)
            w.dirty=False;w.close();QTest.qWait(50)

    def test_step4_effect_inspector_controls(self):
        with tempfile.TemporaryDirectory() as state:
            lut=Path(state)/'identity.cube'
            lut.write_text('''TITLE "Identity"\nLUT_3D_SIZE 2\n0 0 0\n0 0 1\n0 1 0\n0 1 1\n1 0 0\n1 0 1\n1 1 0\n1 1 1\n''',encoding='utf-8')
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.blue)]);self.wait_job(w)
            w.drop_asset(0,0,1);w.select_clip(w.clips[0].uid)
            w.freeze_enabled.setChecked(True);w.freeze_duration.setValue(.35);w.reverse_clip.setChecked(True)
            w.filter_preset.setCurrentIndex(w.filter_preset.findData('warm'));w.lut_path.setText(str(lut))
            w.chroma_key_enabled.setChecked(True);w.chroma_key_color.setText('#00ff00')
            w.chroma_key_similarity.setValue(15);w.chroma_key_blend.setValue(20)
            w.mask_type.setCurrentIndex(w.mask_type.findData('ellipse'));w.mask_x.setValue(8);w.mask_y.setValue(8)
            w.mask_width.setValue(84);w.mask_height.setValue(84);w.mask_feather.setValue(8)
            w.speed_ramp_time.setValue(.4);w.speed_ramp_value.setValue(2);w.set_speed_ramp()
            w.apply_properties()
            clip=w.current_clip()
            self.assertTrue(clip.freeze_frame and clip.reverse and clip.chroma_key_enabled)
            self.assertAlmostEqual(clip.freeze_duration,.35,places=2)
            self.assertEqual(clip.filter_preset,'warm');self.assertEqual(Path(clip.lut_path),lut.resolve())
            self.assertEqual(clip.mask_type,'ellipse');self.assertEqual(len(clip.speed_keyframes),1)
            self.assertFalse(errors)
            w.fill_inspector();self.assertEqual(w.speed_ramp_list.count(),1)
            self.assertTrue(w.lut_browse_button.isEnabled());self.assertTrue(w.freeze_duration.isEnabled())
            w.dirty=False;w.close();QTest.qWait(50)

    def test_step5_effect_presets_adjustment_curves_and_new_transitions(self):
        with tempfile.TemporaryDirectory() as state:
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.blue)]);self.wait_job(w)
            w.drop_asset(0,0,1);w.select_clip(w.clips[0].uid)
            w.effect_preset.setCurrentIndex(w.effect_preset.findData('cinematic'));w.apply_effect_preset()
            clip=w.current_clip();self.assertEqual(clip.effect_preset,'cinematic');self.assertEqual(clip.filter_preset,'cinematic')
            w.stabilization.setValue(35);w.apply_properties();self.assertAlmostEqual(w.current_clip().stabilization,.35,places=2)
            w.keyframe_curve.setCurrentIndex(w.keyframe_curve.findData('ease_in_out'));w.keyframe_time.setValue(.4);w.set_keyframe()
            self.assertEqual(w.current_clip().keyframes[0]['curve'],'ease_in_out')
            w.add_adjustment_layer();adjustment=next(value for value in w.clips if value.source_type=='adjustment')
            self.assertEqual(w.current_clip().uid,adjustment.uid);self.assertTrue(w.effect_preset.isEnabled());self.assertFalse(w.transform_scale.isEnabled())
            w.effect_preset.setCurrentIndex(w.effect_preset.findData('dream'));w.apply_effect_preset()
            self.assertEqual(w.current_clip().effect_preset,'dream');self.assertAlmostEqual(w.current_clip().blur,.65,places=2)
            w.import_paths([str(test_core.EditorCoreTest.red)]);self.wait_job(w)
            w.drop_asset(1,3,1)
            incoming=next(value for value in w.clips if value.path==str(test_core.EditorCoreTest.red.resolve()))
            w.select_clip(incoming.uid)
            w.transition_type.setCurrentIndex(w.transition_type.findData('circle_open'));w.transition_duration.setValue(.25);w.apply_properties()
            self.assertEqual(w.current_clip().transition_type,'circle_open');self.assertIn('circle_open',[w.transition_type.itemData(i) for i in range(w.transition_type.count())])
            self.assertFalse(errors)
            w.cancel_preview(wait=True);w.dirty=False;w.close();QTest.qWait(50)

    def test_step5_audio_inspector_controls(self):
        with tempfile.TemporaryDirectory() as state:
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.tone)]);self.wait_job(w)
            w.drop_asset(0,0,-1);w.select_clip(w.clips[0].uid)
            self.assertTrue(w.audio_noise_reduction.isEnabled())
            w.audio_noise_reduction.setValue(8);w.audio_eq_low.setValue(3);w.audio_eq_mid.setValue(-2);w.audio_eq_high.setValue(4)
            w.audio_compressor_enabled.setChecked(True);w.audio_compressor_threshold.setValue(-20);w.audio_compressor_ratio.setValue(5)
            w.audio_ducking.setValue(90);w.audio_channel_mode.setCurrentIndex(w.audio_channel_mode.findData('mono'));w.audio_pan.setValue(-25)
            w.apply_properties()
            clip=w.current_clip()
            self.assertAlmostEqual(clip.audio_noise_reduction,8)
            self.assertEqual((clip.audio_eq_low,clip.audio_eq_mid,clip.audio_eq_high),(3,-2,4))
            self.assertTrue(clip.audio_compressor_enabled)
            self.assertEqual((clip.audio_compressor_threshold,clip.audio_compressor_ratio),(-20,5))
            self.assertAlmostEqual(clip.audio_ducking,.9);self.assertEqual(clip.audio_channel_mode,'mono');self.assertAlmostEqual(clip.audio_pan,-.25)
            w.fill_inspector()
            self.assertEqual(w.audio_channel_mode.currentData(),'mono');self.assertAlmostEqual(w.audio_ducking.value(),90)
            self.assertFalse(errors)
            w.dirty=False;w.close();QTest.qWait(50)

    def test_step3_audio_mixer_controls_undo_and_meters(self):
        with tempfile.TemporaryDirectory() as state:
            w=Editor(state,recovery=False);w.show();QTest.qWait(100)
            errors=[];w.error=lambda text:errors.append(str(text))
            w.import_paths([str(test_core.EditorCoreTest.tone)]);self.wait_job(w)
            w.drop_asset(0,0,-1);w.open_mixer();QTest.qWait(80)
            dialog=w.mixer_dialog;self.assertIsNotNone(dialog);self.assertTrue(w.mixer_button.isEnabled())
            controls=dialog.track_controls[-1]
            controls['volume_spin'].setValue(55);controls['pan_spin'].setValue(-25);controls['solo'].setChecked(True)
            dialog.master_volume.setValue(80);dialog.loudness_box.setChecked(True);dialog.loudness_target.setValue(-14)
            self.assertAlmostEqual(w.track_states[-1]['volume'],.55);self.assertAlmostEqual(w.track_states[-1]['pan'],-.25)
            self.assertTrue(w.track_states[-1]['solo']);self.assertAlmostEqual(w.master_mixer['volume'],.8)
            self.assertTrue(w.master_mixer['loudness_normalization']);self.assertAlmostEqual(w.master_mixer['loudness_target'],-14)
            w.set_playhead(.2);dialog.update_meters();self.assertGreaterEqual(dialog.master_meter.level,0)
            w.undo();self.assertAlmostEqual(w.master_mixer['volume'],1.0);self.assertFalse(w.track_states[-1]['solo'])
            dialog.close();w.dirty=False;w.close();QTest.qWait(50)

    def test_step6_export_dialog_controls(self):
        dialog=ExportDialog();dialog.show();QTest.qWait(50)
        dialog.format_combo.setCurrentIndex(dialog.format_combo.findData('mkv'))
        dialog.codec_combo.setCurrentIndex(dialog.codec_combo.findData('hevc'))
        dialog.fps.setValue(60);dialog.bitrate.setValue(25000);dialog.hdr.setChecked(True)
        dialog.accept()
        self.assertEqual(dialog.export_settings['format'],'mkv');self.assertEqual(dialog.export_settings['video_codec'],'hevc')
        self.assertEqual(dialog.export_settings['fps'],60);self.assertEqual(dialog.export_settings['bitrate_kbps'],25000)
        self.assertTrue(dialog.export_settings['hdr']);dialog.close()

    def test_step7_project_management_controls(self):
        with tempfile.TemporaryDirectory() as state:
            w=Editor(state,recovery=False);w.show();QTest.qWait(50)
            self.assertTrue(w.relink_button.isEnabled());self.assertTrue(w.archive_button.isEnabled())
            self.assertTrue(w.render_queue_button.isEnabled());self.assertIn('360p',w.proxy_profile_combo.itemText(0))
            self.assertIn('Cache',w.cache_status.text())
            self.assertFalse(w.proxy_box.isEnabled())
            w.import_paths([str(test_core.EditorCoreTest.blue)]);self.wait_job(w)
            w.drop_asset(0,0,1)
            self.assertTrue(w.proxy_box.isEnabled())
            missing=Path(state)/'moved-blue.mp4'
            w.clips[0]=replace(w.clips[0],path=str(missing))
            w.refresh_media()
            self.assertTrue(w.missing_media)
            self.assertTrue(w.relink_media(mapping={str(missing):str(test_core.EditorCoreTest.blue)}))
            self.assertFalse(w.missing_media)
            self.assertEqual(w.clips[0].path,str(test_core.EditorCoreTest.blue.resolve()))
            w.proxy_box.setChecked(True);self.wait_job(w)
            self.assertTrue(w.proxy_map);self.assertTrue(all(Path(path).is_file() for path in w.proxy_map.values()))
            w.proxy_box.setChecked(False)
            target=Path(state)/'queued-export.mp4'
            queued_clip=replace(w.clips[0],end=.5)
            w.render_queue.append({'target':target,'clips':[queued_clip],'tracks':list(w.tracks),
                'track_states':{track:dict(value) for track,value in w.track_states.items()},
                'size':(160,90),'settings':{'format':'mp4','video_codec':'h264','fps':24,
                'bitrate_kbps':1200,'encoder':'software','hdr':False},'label':'Queue-Test'})
            w.update_render_queue_button();w.process_render_queue();self.wait_job(w)
            self.assertTrue(target.is_file());self.assertEqual(w.render_queue_button.text(),'Render-Queue (0)')
            w.dirty=False;w.close();QTest.qWait(50)


if __name__=='__main__':unittest.main()
