"""Editor integration for Smooth Workflow. No changes to the user's source media."""
import inspect
import os
import time
import uuid
import subprocess
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QByteArray
from PySide6.QtGui import QFont, QFontMetricsF, QImage, QPixmap, QAction
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QDialog, QLabel, QPushButton, QToolButton, QLineEdit, QCheckBox, QComboBox,
    QMenu, QListWidget, QListWidgetItem, QMessageBox, QDoubleSpinBox)
from PySide6.QtMultimedia import QMediaPlayer
from core import PRESETS, MIN_CLIP, length, validate_timeline, missing_project_media, render
from ux import (FineDoubleSpinBox, InputGuard, InlineTask, FrameProbe, load_preferences,
                save_preferences, scaled_style, fade_in, error_guidance, without_visual_effects)
from style import STYLE


HISTORY_NAMES = {
    'apply_properties':'Clip-Einstellungen', 'commit_drag':'Clip verschieben / trimmen / Fade',
    'split':'Clip teilen', 'remove':'Auswahl entfernen', 'add_text':'Text hinzufügen',
    'drop_asset':'Medium einfügen', 'apply_effect_preset':'Effekt-Preset',
    'set_keyframe':'Keyframe setzen', 'set_volume_keyframe':'Audio-Keyframe setzen',
    'reset_transform':'Bild-Einstellungen zurücksetzen', 'ripple_delete':'Ripple löschen',
    'group_selection':'Clips gruppieren', 'ungroup_selection':'Gruppe lösen',
    'toggle_track_mute':'Spur stummschalten', 'toggle_track_lock':'Spur sperren',
    'paste_selection':'Clips einfügen', 'add_marker':'Marker setzen',
    'import_done':'Medien importieren', 'inline_apply':'Clip direkt bearbeiten',
    'commit_view_transform':'In der Vorschau ausrichten', '_commit_trim_replacements':'Präzisionsschnitt',
}


class SmoothWorkbench:
    def init_smooth_state(self):
        self.preferences_path=self.state_dir/'workspace.json'
        self.ui_preferences=load_preferences(self.preferences_path)
        self.history_labels=[]; self.future_labels=[]; self.history_dialog=None
        self.independent_jobs={}; self.visual_pending={}; self.visual_job=None
        self.last_autosave=None; self.autosave_revision=-1
        self._compare_saved=None; self.compare_job=None; self.compare_active=False
        self._zoom_anchor=None; self.follow_suspended=False; self._following=False
        self._inspector_filling=False; self._trim_token=None; self._normal_sizes=None
        self.project_session=0

    def init_smooth_ui(self):
        self.tasks_host=QWidget(); self.tasks_layout=QVBoxLayout(self.tasks_host)
        self.tasks_layout.setContentsMargins(0,0,0,0); self.tasks_layout.setSpacing(0)
        self.centralWidget().layout().insertWidget(2,self.tasks_host); self.tasks_host.hide()
        self.input_guard=InputGuard(self); QApplication.instance().installEventFilter(self.input_guard)
        self.trim_probe=FrameProbe(self); self.trim_probe.ready.connect(self.trim_frame_ready)
        self.trim_hint=QLabel(self.video_stack); self.trim_hint.setObjectName('trimPreview')
        self.trim_hint.setStyleSheet('QLabel { background: #10232e; border: 1px solid #7ddfca; padding: 5px; }')
        self.trim_hint.hide()
        self.timeline.trim_preview.connect(self.show_trim_preview)
        self.timeline.gesture_done.connect(self.hide_trim_preview)
        self.timeline.navigation_started.connect(self.suspend_follow)
        self.scroll.horizontalScrollBar().sliderPressed.connect(self.suspend_follow)
        self.timeline.zoom_at_request.connect(self.zoom_at_pointer)
        self.video.transform_started.connect(self.player.pause)
        self.video.transform_committed.connect(self.commit_view_transform)

        bar=QWidget(); row=QHBoxLayout(bar); row.setContentsMargins(8,2,8,3)
        row.addWidget(QLabel('CLIP'))
        self.inline_name=QLineEdit(); self.inline_name.setMaxLength(200); self.inline_name.setPlaceholderText('Clipname')
        self.inline_name.setAccessibleName('Clipname direkt bearbeiten'); self.inline_name.setMaximumWidth(260)
        self.inline_name.editingFinished.connect(self.inline_apply); row.addWidget(self.inline_name,1)
        self.inline_volume=FineDoubleSpinBox(); self.inline_volume.setRange(0,100); self.inline_volume.setDecimals(1)
        self.inline_volume.setSuffix(' %'); self.inline_volume.reset_value=100
        self.inline_volume.setToolTip('Clip-Lautstärke · Shift: fein · Doppelklick: 100 %')
        self.inline_volume.editingFinished.connect(self.inline_apply); row.addWidget(self.inline_volume)
        self.inline_enabled=QCheckBox('Aktiv'); self.inline_enabled.setToolTip('Clip in Vorschau und Export verwenden')
        self.inline_enabled.clicked.connect(self.inline_apply); row.addWidget(self.inline_enabled)
        self.inline_color=QToolButton(); self.inline_color.setText('Farbe'); menu=QMenu(self.inline_color)
        for name,color in (('Standard',''),('Türkis','#70c8e2'),('Grün','#72d0ac'),('Violett','#c898ed'),('Gold','#e6bf67'),('Rot','#ff909c')):
            menu.addAction(name,lambda checked=False,c=color:self.inline_apply(color=c))
        self.inline_color.setMenu(menu); self.inline_color.setPopupMode(QToolButton.InstantPopup); row.addWidget(self.inline_color)
        row.addStretch()
        self.follow_box=QCheckBox('Abspielkopf folgen'); self.follow_box.setChecked(True)
        self.follow_box.toggled.connect(lambda *_:setattr(self,'follow_suspended',False)); row.addWidget(self.follow_box)
        self.scroll.parentWidget().layout().insertWidget(1,bar)

        settings=QToolButton(); settings.setText('⋯'); settings.setToolTip('Verlauf, Projektstatus und Bedienung')
        settings.setAccessibleName(settings.toolTip()); settings.setFixedSize(32,30)
        settings_menu=QMenu(settings)
        settings_menu.addAction('Bearbeitungsverlauf · Strg+Alt+Z',self.show_history)
        settings_menu.addAction('Projekt-Statuszentrale',self.show_project_status)
        settings_menu.addSeparator()
        self.reduced_motion=QAction('Bewegungen reduzieren',settings_menu); self.reduced_motion.setCheckable(True)
        settings_menu.addAction(self.reduced_motion)
        scale_menu=settings_menu.addMenu('Lesbarkeit / UI-Größe')
        for value in (100,115,130,150):
            scale_menu.addAction(f'{value} %',lambda checked=False,v=value:self.set_ui_scale(v))
        settings.setMenu(settings_menu); settings.setPopupMode(QToolButton.InstantPopup)
        self.modebar.layout().addWidget(settings)

        self.performance_combo=QComboBox()
        for title,value in (('Ausgewogen','balanced'),('Flüssig · 360p-Proxys','smooth'),('Detail · Originale','detail')):
            self.performance_combo.addItem(title,value)
        self.performance_combo.setToolTip('Vorschau-Leistung · Export verwendet immer Originalmedien')
        self.performance_combo.currentIndexChanged.connect(self.performance_changed)
        preview_row=QHBoxLayout(); preview_row.addWidget(self.performance_combo,1)
        self.compare_button=QPushButton('Original vergleichen · B halten')
        self.compare_button.setToolTip('Gedrückt halten: Timeline ohne Bild-Effekte. Ton, Timing und Bildposition bleiben erhalten.')
        self.compare_button.pressed.connect(self.compare_pressed); self.compare_button.released.connect(self.compare_released)
        preview_row.addWidget(self.compare_button)
        options=QToolButton(); options.setText('⋯'); options.setCheckable(True)
        options.setToolTip('Erweiterte Vorschauoptionen · Proxys, GPU und Cache')
        options.toggled.connect(self.preview_tools.setVisible); preview_row.addWidget(options)
        self.preview_tools.hide(); self.video_stack.parentWidget().layout().addLayout(preview_row)

        for name,value in vars(self).copy().items():
            if isinstance(value,FineDoubleSpinBox):
                value.reset_value=100 if name in ('volume','inline_volume','opacity') else 50 if name in ('transform_x','transform_y','text_x','text_y','mask_x','mask_y') else 1 if name in ('speed','transform_scale','contrast','saturation') else value.value()
                if name=='audio_compressor_threshold': value.reset_value=-18
                if name=='audio_compressor_ratio': value.reset_value=4
                if name=='audio_normalize_target': value.reset_value=-16
                value.setToolTip((value.toolTip()+'\n' if value.toolTip() else '')+'Shift: fein einstellen · Doppelklick: Standardwert · Esc: Eingabe abbrechen')
                value.setAccessibleName(name.replace('_',' '))
        for entry in self.inspector_sections:
            body=entry['body']
            entry['toggle'].toggled.connect(lambda checked,b=body:fade_in(b,self.reduced_motion.isChecked()) if checked else None)
        self.autosave_heartbeat=QTimer(self); self.autosave_heartbeat.setInterval(30000)
        self.autosave_heartbeat.timeout.connect(self.autosave); self.autosave_heartbeat.start()
        self.restore_workspace()

    def save_workspace(self):
        if not hasattr(self,'follow_box'): return
        data={'top':self._normal_sizes if self.focus_mode and self._normal_sizes else self.top.sizes(),
              'vertical':self.vertical.sizes(),'edit_mode':self.edit_mode_combo.currentData(),
              'workspace':self.workspace_preset_combo.currentData(),'media_view':self.media_view_combo.currentData(),
              'favorites':sorted(self.favorite_assets),'zoom':self.zoom_slider.value(),
              'sections':{e['toggle'].text():e['toggle'].isChecked() for e in self.inspector_sections},
              'geometry':bytes(self.saveGeometry().toBase64()).decode(),
              'follow':self.follow_box.isChecked(),'reduced_motion':self.reduced_motion.isChecked(),
              'ui_scale':getattr(self,'ui_scale',100),'performance':self.performance_combo.currentData(),
              'export':getattr(self,'last_export_settings',{})}
        try: save_preferences(self.preferences_path,data)
        except OSError as exc: self.statusBar().showMessage('Oberfläche konnte nicht gespeichert werden: '+str(exc),5000)

    def restore_workspace(self):
        prefs=self.ui_preferences
        for key,combo in (('edit_mode',self.edit_mode_combo),('workspace',self.workspace_preset_combo),('media_view',self.media_view_combo)):
            index=combo.findData(prefs.get(key))
            if index>=0: combo.setCurrentIndex(index)
        self.favorite_assets=set(v for v in prefs.get('favorites',[]) if isinstance(v,str)) if isinstance(prefs.get('favorites',[]),list) else set()
        sections=prefs.get('sections',{})
        if isinstance(sections,dict):
            for entry in self.inspector_sections:
                if entry['toggle'].text() in sections: entry['toggle'].setChecked(bool(sections[entry['toggle'].text()]))
        zoom=prefs.get('zoom',60)
        if isinstance(zoom,(int,float)): self.zoom_slider.setValue(max(2,min(200,int(zoom))))
        self.follow_box.setChecked(bool(prefs.get('follow',True)))
        self.reduced_motion.setChecked(bool(prefs.get('reduced_motion',False)))
        scale=prefs.get('ui_scale',100); self.set_ui_scale(scale if scale in (100,115,130,150) else 100)
        geometry=prefs.get('geometry')
        if isinstance(geometry,str): self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        for key,splitter,count in (('top',self.top,3),('vertical',self.vertical,2)):
            sizes=prefs.get(key)
            if isinstance(sizes,list) and len(sizes)==count and all(isinstance(v,int) and v>=0 for v in sizes): splitter.setSizes(sizes)
        self.last_export_settings=prefs.get('export',{}) if isinstance(prefs.get('export'),dict) else {}
        index=self.performance_combo.findData(prefs.get('performance','balanced'))
        if index>=0: self.performance_combo.setCurrentIndex(index)

    def set_ui_scale(self,percent):
        self.ui_scale=percent
        self.setStyleSheet(scaled_style(STYLE,percent))
        self.timeline.ui_scale=percent/100
        self.timeline.ROW=round(70*percent/100); self.timeline.LEFT=round(150*percent/100)
        for control in self.findChildren(QToolButton):
            if control.objectName() in ('headerToolButton','timelineToolButton','timelineToolToggle','timelineToolDanger','sourceToolButton','sourceToolDanger','contextAction','timelineMenuButton'):
                control.setFixedSize(round(34*percent/100),round(30*percent/100))
        self.timeline.refresh(self.clips,self.tracks,self.current,self.track_states,self.track_names,self.selection,self.markers)

    def suspend_follow(self):
        if not self._following: self.follow_suspended=True

    def follow_playhead(self):
        if not hasattr(self,'follow_box') or not self.follow_box.isChecked() or self.follow_suspended: return
        if self.timeline.drag or self.timeline.pan_drag is not None: return
        bar=self.scroll.horizontalScrollBar(); width=self.scroll.viewport().width()
        x=self.timeline.LEFT+self.playhead*self.timeline.scale
        if x>bar.value()+width*.85 or x<bar.value()+20:
            self._following=True; bar.setValue(round(x-width*.4)); self._following=False

    def zoom_at_pointer(self,direction,x):
        self._zoom_anchor=(self.timeline.time_at(x),x-self.scroll.horizontalScrollBar().value())
        self.zoom_slider.setValue(self.zoom_slider.value()+direction*5)
        self._zoom_anchor=None

    def refresh_inline(self):
        if not hasattr(self,'inline_name'): return
        clip=self.current_clip(); editable=clip is not None and len(self.selection)==1 and not self.worker and not self.selection_locked()
        for control in (self.inline_name,self.inline_volume,self.inline_enabled,self.inline_color): control.setEnabled(editable)
        if clip:
            self.end.reset_value=clip.duration if clip.kind!='text' else min(clip.duration,clip.start+3)
            self.inline_name.setText(clip.display_name or clip.compound_name or (clip.text if clip.kind=='text' else Path(clip.path).name))
            self.inline_volume.setValue(clip.volume*100); self.inline_volume.setEnabled(editable and clip.has_audio)
            self.inline_enabled.setChecked(clip.enabled)
        else: self.inline_name.clear()
        self.refresh_view_geometry()

    def inline_apply(self,*_,color=None):
        clip=self.current_clip()
        if not clip or self.worker or self.selection_locked() or len(self.selection)!=1: return
        values={'display_name':self.inline_name.text().strip(),'volume':self.inline_volume.value()/100,
                'enabled':self.inline_enabled.isChecked()}
        if color is not None: values['label_color']=color
        candidate=replace(clip,**values)
        if candidate==clip: return
        self.checkpoint('Clip direkt bearbeiten')
        self.clips=[candidate if c.uid==clip.uid else c for c in self.clips]; self.changed()

    def show_history(self):
        if self.history_dialog is None:
            dialog=QDialog(self); dialog.setWindowTitle('Bearbeitungsverlauf'); dialog.resize(440,420)
            layout=QVBoxLayout(dialog); layout.addWidget(QLabel('Doppelklick: zu diesem Stand wechseln.'))
            self.history_list=QListWidget(); layout.addWidget(self.history_list)
            self.history_list.itemDoubleClicked.connect(lambda item:self.jump_history(int(item.data(Qt.UserRole))))
            self.history_dialog=dialog
        self.refresh_history(); self.history_dialog.show(); self.history_dialog.raise_()

    def refresh_history(self):
        if self.history_dialog is None: return
        self.history_list.clear(); titles=['Anfang des verfügbaren Verlaufs']+self.history_labels+list(reversed(self.future_labels))
        for index,title in enumerate(titles):
            item=QListWidgetItem(('● ' if index==len(self.history) else '  ')+title)
            item.setData(Qt.UserRole,index); self.history_list.addItem(item)
        self.history_list.setCurrentRow(len(self.history))

    def jump_history(self,index):
        if self.worker: return
        target=max(0,min(len(self.history)+len(self.future),index))
        while len(self.history)>target: self.undo()
        while len(self.history)<target: self.redo()

    def show_project_status(self):
        dialog=QDialog(self); dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setWindowTitle('Projekt-Statuszentrale'); dialog.resize(530,350)
        layout=QVBoxLayout(dialog); details=QLabel(); details.setWordWrap(True); details.setTextFormat(Qt.PlainText); layout.addWidget(details)
        for title,callback in (('Projekt speichern',self.save),('Medien neu verknüpfen',self.relink_media),
                               ('Render-Queue öffnen',self.show_render_queue),('Cache prüfen / leeren',self.clear_cache)):
            action=QPushButton(title); action.clicked.connect(lambda checked=False,cb=callback:cb()); layout.addWidget(action)
        def refresh():
            missing=missing_project_media(self.clips,self.assets)
            saved=time.strftime('%H:%M:%S',time.localtime(self.last_autosave)) if self.last_autosave else 'noch keine Sicherung in dieser Sitzung'
            details.setText(f'Projekt: {self.project_path or "noch nicht als Datei gespeichert"}\n'
                f'Änderungen: {"ungespeichert" if self.dirty else "gespeichert"}\nAutosave: {saved}\n'
                f'Medien: {len(self.assets)} · fehlende Dateien: {len(missing)}\n'
                f'Vorschau: {"aktuell" if self.preview_is_current() else "wird bei Bedarf aktualisiert"}\n'
                f'Proxys: {len(self.proxy_map)} · Profil: {self.proxy_profile}\n'
                f'Hintergrundaufgaben: {len(self.independent_jobs)+(1 if self.worker else 0)}\n'
                f'Exportwarteschlange: {len(self.render_queue)} · {self.cache_status.text()}')
        timer=QTimer(dialog); timer.setInterval(1000); timer.timeout.connect(refresh); timer.start()
        refresh(); dialog.show()

    def present_error(self,message):
        title,hint,action=error_guidance(message)
        box=QMessageBox(QMessageBox.Warning,'Framecut',title,QMessageBox.Close,self)
        box.setInformativeText(hint); box.setDetailedText(str(message)); box.setWindowModality(Qt.NonModal)
        if action:
            label,callback={'export':('Exportziel neu wählen',self.start_export),
                            'relink':('Medien verknüpfen',self.relink_media),
                            'status':('Projektstatus öffnen',self.show_project_status)}[action]
            fix=box.addButton(label,QMessageBox.ActionRole); fix.clicked.connect(lambda checked=False:callback())
        box.setAttribute(Qt.WA_DeleteOnClose); box.show()

    def new_task(self,title):
        task=InlineTask(title,self.tasks_host); self.tasks_layout.addWidget(task); self.tasks_host.show(); task.show()
        return task

    def start_independent_job(self,key,title,operation,callback):
        if key in self.independent_jobs or self._closing: return False
        job=self.job_type(operation); task=self.new_task(title)
        self.independent_jobs[key]=(job,task)
        session=self.project_session
        task.canceled.connect(job.cancel.set); job.progress.connect(task.setValue)
        def finished(result):
            job.wait(); self.independent_jobs.pop(key,None); task.close(); task.deleteLater(); job.deleteLater()
            if not self.independent_jobs and not self.worker: self.tasks_host.hide()
            if not self._closing and (key=='export' or session==self.project_session): callback(result)
        job.result.connect(finished); job.start(); return True

    def performance_changed(self,*_):
        mode=self.performance_combo.currentData()
        self.quick_preview_box.setChecked(mode!='detail')
        if mode=='smooth':
            self.proxy_profile_combo.setCurrentIndex(self.proxy_profile_combo.findData('360p'))
            if self.proxy_box.isEnabled(): self.proxy_box.setChecked(True)
        elif mode=='detail': self.proxy_box.setChecked(False)
        self.statusBar().showMessage('Vorschau-Profil geändert · Export bleibt in Originalqualität.',4000)

    def ensure_missing_proxies(self):
        if self._closing or self.worker or not self.proxy_enabled or 'proxy' in self.independent_jobs: return
        sources={str(Path(c.path).resolve()) for c in getattr(self,'assets',[])+self.clips
                 if c.path and c.kind in ('video','audio') and c.source_type not in ('image','image_sequence')}
        if sources-set(self.proxy_map): self.start_proxy_generation()

    @staticmethod
    def visual_key(path):
        """Return one canonical key for posters and waveforms.

        Projects created before the media-bin refresh could contain a relative
        or differently-normalized path. Keeping one key here prevents a
        generated waveform from being stored under a name the timeline cannot
        find later.
        """
        if not path:
            return ''
        try:
            return str(Path(path).expanduser().resolve())
        except (OSError, RuntimeError, TypeError):
            return str(path)

    def queue_visuals(self,assets):
        if not hasattr(self,'visual_pending'): return
        for asset in assets:
            source_path=self.visual_key(asset.path)
            if source_path and (source_path not in self.thumbnails
                                or ((asset.has_audio or asset.kind == 'audio')
                                    and source_path not in self.waveforms)):
                self.visual_pending[source_path]=replace(asset,path=source_path)
        if self.visual_job or not self.visual_pending or self._closing: return
        assets=list(self.visual_pending.values()); self.visual_pending.clear(); root=self.thumbnail_cache
        thumbnails=dict(self.thumbnails); waveforms=dict(self.waveforms)
        def operation(progress,cancel):
            posters={}; waves={}
            for index,asset in enumerate(assets):
                if cancel.is_set(): break
                try:
                    source_path=self.visual_key(asset.path)
                    stat=Path(source_path).stat(); key=f'{source_path}:{stat.st_mtime_ns}:{stat.st_size}'
                    if asset.kind=='video' and source_path not in thumbnails:
                        target=root/(uuid.uuid5(uuid.NAMESPACE_URL,key).hex+'.jpg')
                        if asset.source_type in ('image','image_sequence'):
                            image=QImage(asset.source_paths[0] if asset.source_paths else asset.path)
                        else:
                            if not target.exists():
                                subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-ss',str(min(.5,asset.duration*.08)),
                                    '-i',asset.path,'-frames:v','1','-vf','scale=320:-2','-threads','1',str(target)],check=True,timeout=12,capture_output=True)
                            image=QImage(str(target))
                        if not image.isNull(): posters[source_path]=image.scaled(320,180,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                    if (asset.has_audio or asset.kind=='audio') and source_path not in waveforms:
                        target=root/(uuid.uuid5(uuid.NAMESPACE_URL,key+'-wave-v3').hex+'.png')
                        if not target.exists():
                            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-i',asset.path,
                                '-filter_complex','showwavespic=s=1200x180:colors=63ead4:scale=sqrt:draw=full:filter=peak',
                                '-frames:v','1','-threads','1',str(target)],check=True,timeout=20,capture_output=True)
                        image=QImage(str(target))
                        if not image.isNull(): waves[source_path]=image
                except (OSError,subprocess.SubprocessError): pass
                progress(round((index+1)/len(assets)*100))
            return posters,waves
        job=self.job_type(operation); self.visual_job=job
        def finished(result):
            job.wait(); self.visual_job=None; job.deleteLater()
            if self._closing: return
            if result['ok']:
                posters,waves=result['value']; self.thumbnails.update(posters); self.waveforms.update(waves)
                self.timeline.set_visuals(self.thumbnails,self.waveforms); self.refresh_media(); self.refresh_view_geometry()
            self.queue_visuals([])
        job.result.connect(finished); job.start()

    def show_trim_preview(self,clip,edge):
        original=next((c for c in self.clips if c.uid==clip.uid),clip)
        delta=clip.length-original.length
        self.statusBar().showMessage(f'{"Anfang" if edge=="left" else "Ende"}: {clip.start if edge=="left" else clip.end:.3f} s · Länge {clip.length:.3f} s ({delta:+.3f} s)')
        if clip.kind!='video' or clip.source_type=='adjustment': return
        source=clip.source_paths[0] if clip.source_type=='image_sequence' and clip.source_paths else clip.path
        time_value=clip.start if edge=='left' else max(clip.start,clip.end-1/max(1,clip.source_fps))
        if clip.reverse: time_value=max(clip.start,clip.end-1/max(1,clip.source_fps)) if edge=='left' else clip.start
        if clip.source_type=='image_sequence' and clip.source_paths:
            source=clip.source_paths[min(len(clip.source_paths)-1,round(time_value*clip.source_fps))]; time_value=0
        elif clip.source_type=='image': time_value=0
        self._trim_token=uuid.uuid4().hex
        self.trim_probe.request(source,time_value,self._trim_token)

    def trim_frame_ready(self,token,image):
        if token!=self._trim_token: return
        self.trim_hint.setPixmap(QPixmap.fromImage(image)); self.trim_hint.adjustSize(); self.trim_hint.move(8,8)
        self.trim_hint.setToolTip(self.statusBar().currentMessage()); self.trim_hint.show(); self.trim_hint.raise_()

    def hide_trim_preview(self):
        self._trim_token=None; self.trim_hint.hide()

    def refresh_view_geometry(self):
        clip=self.current_clip(); geometry=None
        valid=clip and len(self.selection)==1 and clip.enabled and not self.worker and not self.track_locked(clip.track)
        if valid and self.mode=='timeline' and clip.position<=self.playhead<clip.finish and not self.compare_active:
            width,height=PRESETS[self.preset.currentText()]
            if clip.kind=='text':
                font=QFont(clip.font_family); font.setPixelSize(clip.font_size)
                metrics=QFontMetricsF(font)
                geometry={'x':clip.x,'y':clip.y,'width':min(.95,metrics.horizontalAdvance(clip.text)/width),'height':min(.95,metrics.height()/height)}
            elif clip.kind=='video' and clip.source_type!='adjustment' and not clip.keyframes and abs(clip.rotation)<.01:
                image=self.thumbnails.get(clip.path)
                aspect=image.width()/max(1,image.height()) if image and not image.isNull() else width/height
                aspect*=max(.01,1-clip.crop_left-clip.crop_right)/max(.01,1-clip.crop_top-clip.crop_bottom)
                h=min(height,width/aspect); w=h*aspect
                geometry={'x':clip.video_x,'y':clip.video_y,'width':w*clip.video_scale/width,'height':h*clip.video_scale/height}
        self.video.set_edit_geometry(geometry)

    def commit_view_transform(self,x,y):
        clip=self.current_clip()
        if not clip or self.worker or self.selection_locked(): return
        candidate=replace(clip,**({'x':x,'y':y} if clip.kind=='text' else {'video_x':x,'video_y':y}))
        if candidate==clip: return
        self.checkpoint('In der Vorschau ausrichten'); self.clips=[candidate if c.uid==clip.uid else c for c in self.clips]; self.changed()

    def compare_pressed(self):
        if self.compare_active or not self.clips or self.worker or self.mode!='timeline': return
        self._compare_saved=(self.player.source(),self.player.position(),self.mode,self.player.playbackState()==QMediaPlayer.PlayingState)
        self.live_preview_timer.stop()
        self.compare_active=True; self.player.pause(); self.video.set_edit_geometry(None)
        self.preview_status.setText('Vergleich ohne Bild-Effekte wird vorbereitet … · Loslassen beendet')
        if self.compare_job: return
        clips=[without_visual_effects(c) for c in self.snapshot()[0]]
        tracks=list(self.tracks); states={t:dict(v) for t,v in self.track_states.items()}; mixer=dict(self.master_mixer)
        target=Path(self.cache.name)/f'compare-{uuid.uuid4().hex}.mp4'; size=self.preview_size(); revision=self.revision
        job=self.job_type(lambda progress,cancel:render(clips,tracks,target,size,progress,cancel,True,states,master_settings=mixer))
        self.compare_job=job
        def finished(result):
            job.wait(); self.compare_job=None; job.deleteLater()
            if self._closing: return
            if self.compare_active and revision==self.revision and result['ok']:
                self.load_player(target,min(self.playhead,length(self.clips)),False)
                self.preview_status.setText('OHNE BILD-EFFEKTE · Taste / Maustaste loslassen für bearbeitete Ansicht')
            elif self.compare_active:
                self.compare_released(); self.statusBar().showMessage('Vergleich konnte nicht geladen werden.',3000)
        job.result.connect(finished); job.start()

    def compare_released(self):
        if not self.compare_active: return
        self.compare_active=False
        if self.compare_job: self.compare_job.cancel.set()
        saved=self._compare_saved; self._compare_saved=None
        if saved:
            url,position,mode,playing=saved; self.mode=mode
            if self.preview_is_current(): self.load_player(self.preview_path,self.playhead,playing)
            elif not url.isEmpty(): self.load_player(url.toLocalFile(),position/1000,playing)
            else: self.player.stop(); self.player.setSource(url); self.video_stack.setCurrentIndex(0)
        self.preview_status.setText('Bearbeitete Ansicht · Vergleich beendet'); self.refresh_view_geometry()
        if self.clips and self.live_preview_box.isChecked() and not self.preview_is_current(): self.live_preview_timer.start()

    def cancel_interaction(self):
        self.timeline.cancel_gesture(); self.video.cancel_transform(); self.compare_released(); self.hide_trim_preview()

    def close_smooth(self):
        self.save_workspace(); self.autosave_heartbeat.stop(); self.trim_probe.stop()
        QApplication.instance().removeEventFilter(self.input_guard)
        for job in [self.visual_job,self.compare_job]+[entry[0] for entry in self.independent_jobs.values()]:
            if job is not None: job.cancel.set()
        for job in [self.visual_job,self.compare_job]+[entry[0] for entry in self.independent_jobs.values()]:
            if job is not None: job.wait()
