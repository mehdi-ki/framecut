"""Integration coverage using generated, temporary audio/video sources."""
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from dataclasses import replace,asdict
from array import array
from core import (Clip,import_clip,import_image_sequence,parse_subtitle_file,subtitle_cues_from_clips,write_subtitle_file,split_clip,edited_clip,slip_clip,roll_edit,slide_edit,snap_time,validate_timeline,
                  save_project,load_project,render,probe,ExportCancelled,length,keyframe_expression,
                  volume_keyframe_expression,speed_keyframe_expression,speed_ramp_duration,curve_progress,
                  audio_effect_filters,tracking_expression,auto_reframe_expression,auto_reframe_aspect,normalize_export_settings,resolve_export_encoder,
                  relink_project_media,archive_project,extract_project_archive,create_proxy_files,
                  PROXY_PROFILES,proxy_path_for,cache_size,prune_cache,preview_acceleration_info,normalize_markers,
                  normalize_master_mixer,master_audio_filters,EFFECT_PRESETS,TRANSITION_TYPES,KEYFRAME_CURVES,color_grading_filters)
from ai_tools import analyze_beats


def ff(*args):
    return subprocess.run(['ffmpeg','-v','error','-y',*map(str,args)],check=True,capture_output=True)


class EditorCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.blue=cls.root/'blue video.mp4';cls.red=cls.root/'red portrait.mp4';cls.tone=cls.root/'music.wav';cls.voice=cls.root/'voice.wav'
        ff('-f','lavfi','-i','color=c=blue:s=320x180:r=30','-t',3,'-c:v','libx264','-threads',1,'-pix_fmt','yuv420p',cls.blue)
        ff('-f','lavfi','-i','color=c=red:s=180x320:r=24','-f','lavfi','-i','sine=frequency=880:sample_rate=48000',
           '-t',1,'-c:v','libx264','-threads',1,'-c:a','aac','-pix_fmt','yuv420p',cls.red)
        ff('-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t',2,cls.tone)
        ff('-f','lavfi','-i','sine=frequency=1200:sample_rate=48000','-t',1,cls.voice)
        cls.tracks=[2,1,-1,-2]

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_import_split_trim_snap_and_collisions(self):
        c=replace(import_clip(self.blue),position=1,start=.3,end=2.5)
        a,b=split_clip(c,2)
        self.assertAlmostEqual(a.finish,b.position);self.assertAlmostEqual(a.end,b.start)
        self.assertNotEqual(a.uid,b.uid);self.assertAlmostEqual(a.length+b.length,c.length)
        with self.assertRaises(ValueError):split_clip(c,1)
        left=edited_clip(c,'left',-10)
        self.assertEqual(left.start,0);self.assertAlmostEqual(left.position,.7)
        right=edited_clip(c,'right',100);self.assertEqual(right.end,c.duration)
        self.assertEqual(edited_clip(c,'move',-100).position,0)
        self.assertEqual(snap_time(1.96,[0,2,4],.1),2)
        self.assertEqual(snap_time(1.5,[0,2,4],.1),1.5)
        with self.assertRaises(ValueError):validate_timeline([c,replace(c,uid='another',position=2)],self.tracks)
        validate_timeline([c,replace(c,uid='another',position=2,track=2)],self.tracks)
        with self.assertRaises(ValueError):validate_timeline([replace(c,track=-1)],self.tracks)

    def test_professional_trim_modes_keep_timeline_geometry(self):
        previous=replace(import_clip(self.blue),start=0,end=1,position=0,track=1)
        middle=replace(import_clip(self.red),start=0,end=1,position=1,track=1,uid='trim-middle')
        following=replace(import_clip(self.blue),start=.4,end=1.4,position=2,track=1,uid='trim-following')

        slipped=slip_clip(replace(import_clip(self.blue),start=.25,end=2.25),.25)
        self.assertAlmostEqual(slipped.start,.5)
        self.assertAlmostEqual(slipped.end,2.5)
        self.assertAlmostEqual(slipped.position,0)
        self.assertAlmostEqual(slipped.length,2.0)

        rolled_left,rolled_right=roll_edit(previous,middle,1.25)
        self.assertAlmostEqual(rolled_left.finish,1.25)
        self.assertAlmostEqual(rolled_right.position,1.25)
        self.assertAlmostEqual(rolled_left.length+rolled_right.length,previous.length+middle.length)

        slid_left,slid_middle,slid_right=slide_edit(previous,middle,following,1/24)
        self.assertAlmostEqual(slid_left.finish,slid_middle.position)
        self.assertAlmostEqual(slid_middle.finish,slid_right.position)
        self.assertAlmostEqual(slid_left.position,previous.position)
        self.assertAlmostEqual(slid_right.finish,following.finish)
        validate_timeline([slid_left,slid_middle,slid_right],self.tracks)

    def test_legacy_migration_and_roundtrip(self):
        old=self.root/'old.framecut'
        old.write_text(json.dumps({'format':'framecut','version':1,'preset':'720p · 16:9','clips':[
            {'path':str(self.blue),'duration':3,'start':.2,'end':1.2,'volume':.7},
            {'path':str(self.blue),'duration':3,'start':1.2,'end':2.7,'volume':1}]}))
        loaded=load_project(old);self.assertTrue(loaded['migrated'])
        self.assertFalse(loaded['clips'][0].has_audio)
        self.assertEqual(loaded['clips'][1].position,1)
        self.assertEqual(length(loaded['clips']),2.5)
        target=self.root/'v2.framecut'
        save_project(target,loaded['clips'],loaded['preset'],self.tracks,loaded['assets'],str(old))
        again=load_project(target)
        self.assertEqual(again['clips'],loaded['clips']);self.assertEqual(again['assets'],loaded['assets'])
        self.assertEqual(again['origin'],str(old));self.assertFalse(again['migrated'])
        self.assertEqual(json.loads(old.read_text())['version'],1)
        missing=json.loads(target.read_text());missing['clips'][0]['path']='missing.mp4';target.write_text(json.dumps(missing))
        with self.assertRaisesRegex(ValueError,'Quelldatei fehlt'):load_project(target)

    def test_step7_relink_archive_and_proxy_media(self):
        """Offline projects can be repaired; archives and proxies are standalone."""
        clip=replace(import_clip(self.blue),end=1.2)
        project=self.root/'step7-relink.framecut'
        save_project(project,[clip],'720p · 16:9',self.tracks,[clip])
        values=json.loads(project.read_text())
        values['clips'][0]['path']='media/blue video-renamed.mp4'
        project.write_text(json.dumps(values))
        with self.assertRaisesRegex(ValueError,'Quelldatei fehlt'):
            load_project(project)
        offline=load_project(project,allow_missing=True)
        self.assertEqual(len(offline['missing_media']),1)
        repaired_clips,repaired_assets=relink_project_media(
            offline['clips'],offline['assets'],{offline['missing_media'][0]:str(self.blue)})
        repaired=self.root/'step7-repaired.framecut'
        save_project(repaired,repaired_clips,offline['preset'],offline['tracks'],repaired_assets)
        self.assertFalse(load_project(repaired,allow_missing=True)['missing_media'])

        archive=self.root/'step7-archive.zip'
        second=replace(import_clip(self.red),end=.7,position=1,track=2)
        archive_project(archive,'step7-demo',[clip,second],'720p · 16:9',self.tracks,
                        [clip,second],track_states={},track_names={})
        extracted=self.root/'step7-extracted'
        contained=Path(extract_project_archive(archive,extracted))
        archived=load_project(contained)
        self.assertTrue(all(Path(item.path).is_file() for item in archived['clips']))
        self.assertTrue(all(str(extracted) in item.path for item in archived['clips']))

        proxies=create_proxy_files([clip],[replace(import_clip(self.tone),end=1)],self.root/'step7-proxies')
        self.assertEqual(len(proxies),2)
        self.assertTrue(all(Path(path).is_file() for path in proxies.values()))
        self.assertTrue(probe(proxies[str(self.blue.resolve())])[1])
        self.assertTrue(probe(proxies[str(self.tone.resolve())])[2])
        proxies_720=create_proxy_files([clip],[],self.root/'step7-proxies',profile='720p')
        self.assertIn('.proxy-720p.mp4',proxies_720[str(self.blue.resolve())])
        self.assertGreaterEqual(probe(proxies_720[str(self.blue.resolve())])[0],.5)

        cache=self.root/'step7-cache'; cache.mkdir()
        (cache/'old-a.bin').write_bytes(b'1234'); (cache/'old-b.bin').write_bytes(b'5678')
        result=prune_cache(cache,5)
        self.assertGreater(result['removed'],0); self.assertLessEqual(cache_size(cache),5)
        self.assertEqual(set(PROXY_PROFILES),{'360p','720p'})
        self.assertIn('.proxy-360p.mp4',proxy_path_for(self.blue,cache,profile='360p'))
        self.assertIn('backend',preview_acceleration_info())

    def test_step2_timeline_markers_roundtrip_and_legacy_default(self):
        clip=replace(import_clip(self.blue),end=3)
        markers=[{'time':2.0,'label':'Höhepunkt','kind':'chapter'},
                 {'time':.5,'label':'Intro','kind':'marker'}]
        project=self.root/'step2-markers.framecut'
        save_project(project,[clip],'720p · 16:9',self.tracks,markers=markers)
        raw=json.loads(project.read_text())
        self.assertEqual(raw['version'],2)
        loaded=load_project(project)
        self.assertEqual([(item['time'],item['kind'],item['label']) for item in loaded['markers']],
                         [(.5,'marker','Intro'),(2.0,'chapter','Höhepunkt')])
        legacy=dict(raw);legacy['version']=2;legacy.pop('markers')
        legacy_path=self.root/'step2-no-markers.framecut';legacy_path.write_text(json.dumps(legacy))
        self.assertEqual(load_project(legacy_path)['markers'],[])
        with self.assertRaises(ValueError):normalize_markers([{'time':4,'label':'zu spät'}],3)

    def test_layer_order_gaps_audio_delay_and_preview(self):
        clips=[replace(import_clip(self.blue),end=2,position=.5),
               replace(import_clip(self.red),position=1,track=2,volume=0),
               replace(import_clip(self.tone),position=.5,track=-1,volume=.5)]
        dest=self.root/'multitrack.mp4';progress=[]
        render(clips,self.tracks,dest,(320,180),progress.append)
        self.assertEqual(progress[-1],100)
        duration,video,audio=probe(dest);self.assertTrue(video and audio);self.assertLess(abs(duration-2.5),.1)
        ff('-i',dest,'-f','null','-')
        def pixel(time):
            return ff('-ss',time,'-i',dest,'-frames:v',1,'-vf','crop=2:2:159:89,scale=1:1',
                      '-pix_fmt','rgb24','-f','rawvideo','-').stdout[:3]
        self.assertLess(max(pixel(.2)),15) # Gap is black, not a frozen clip.
        self.assertGreater(pixel(.7)[2],200) # Base video.
        self.assertGreater(pixel(1.4)[0],200) # Upper track wins.
        self.assertGreater(pixel(2.2)[2],200) # Lower returns after upper ends.
        def rms(start):
            data=ff('-ss',start,'-i',dest,'-t',.15,'-vn','-ar',48000,'-ac',1,'-f','f32le','-').stdout
            vals=array('f');vals.frombytes(data);return (sum(v*v for v in vals)/len(vals))**.5
        self.assertLess(rms(.1),.002);self.assertGreater(rms(.7),.02) # Delayed music starts correctly.
        preview=self.root/'preview.mp4';render(clips,self.tracks,preview,(160,90),preview=True)
        self.assertLess(abs(probe(preview)[0]-duration),.08)

    def test_mix_is_additive_and_muting_works(self):
        a=replace(import_clip(self.tone),end=1,volume=.25)
        b=replace(a,track=-2,uid='second')
        target=self.root/'mix.mp4'
        render([a,b],self.tracks,target,(160,90))
        def rms(path):
            vals=array('f');vals.frombytes(ff('-i',path,'-ss',.1,'-t',.5,'-vn','-ac',1,'-f','f32le','-').stdout)
            return (sum(v*v for v in vals)/len(vals))**.5
        mixed=rms(target)
        render([a,replace(b,volume=0)],self.tracks,target,(160,90))
        single=rms(target);self.assertGreater(mixed/single,1.8);self.assertLess(mixed/single,2.2)

    def test_track_states_mute_render_and_roundtrip(self):
        video=replace(import_clip(self.blue),end=1,position=0,track=1)
        audio=replace(import_clip(self.tone),end=1,position=0,track=-1,volume=.8)
        tracks=[1,-1]
        states={1:{'muted':False,'locked':False},-1:{'muted':True,'locked':True}}
        muted_target=self.root/'muted-track.mp4';render([video,audio],tracks,muted_target,(160,90),track_states=states)
        def rms(path):
            vals=array('f');vals.frombytes(ff('-i',path,'-ss',.1,'-t',.5,'-vn','-ac',1,'-f','f32le','-').stdout)
            return (sum(v*v for v in vals)/len(vals))**.5
        self.assertLess(rms(muted_target),.002)
        audible_target=self.root/'audible-track.mp4';render([video,audio],tracks,audible_target,(160,90))
        self.assertGreater(rms(audible_target),.02)
        project=self.root/'track-states.framecut';save_project(project,[video,audio],'720p · 16:9',tracks,track_states=states)
        loaded=load_project(project)
        for track,state in states.items():
            for key,value in state.items():
                self.assertEqual(loaded['track_states'][track][key],value)
        self.assertEqual(loaded['mixer'],normalize_master_mixer(None))

    def test_step3_audio_mixer_solo_faders_pan_master_and_loudness(self):
        """Track strips, solo logic and the master strip reach FFmpeg and disk."""
        music=replace(import_clip(self.tone),end=1,track=-1,volume=.6)
        voice=replace(import_clip(self.voice),end=1,track=-2,volume=.6,uid='mixer-voice')
        tracks=[-1,-2]
        states={-1:{'muted':False,'locked':False,'solo':True,'volume':.5,'pan':-.4},
                -2:{'muted':False,'locked':False,'solo':False,'volume':1.0,'pan':0.0}}
        settings={'volume':.8,'pan':.25,'loudness_normalization':False,'loudness_target':-16}
        target=self.root/'step3-mixer.mp4';render([music,voice],tracks,target,(160,90),track_states=states,master_settings=settings)
        def band_rms(path,frequency):
            values=array('f');values.frombytes(ff('-i',path,'-ss','0.1','-t','0.5','-vn','-ac','1',
                                                   '-af',f'bandpass=frequency={frequency}:width_type=h:width=100',
                                                   '-f','f32le','-').stdout)
            return (sum(value*value for value in values)/len(values))**.5
        self.assertGreater(band_rms(target,440),.01)
        self.assertLess(band_rms(target,1200),.005)
        filters=master_audio_filters({'volume':1,'pan':0,'loudness_normalization':True,'loudness_target':-14})
        self.assertTrue(any(value.startswith('loudnorm=I=-14.00') for value in filters))
        project=self.root/'step3-mixer.framecut'
        save_project(project,[music,voice],'720p · 16:9',tracks,track_states=states,mixer=settings)
        loaded=load_project(project)
        self.assertEqual(loaded['track_states'][-1]['solo'],True)
        self.assertAlmostEqual(loaded['track_states'][-1]['volume'],.5)
        self.assertAlmostEqual(loaded['track_states'][-1]['pan'],-.4)
        self.assertEqual(loaded['mixer'],normalize_master_mixer(settings))

    def test_still_images_sequences_overlays_and_track_names(self):
        overlay=self.root/'overlay.png'; frame_two=self.root/'frame-02.png'
        ff('-f','lavfi','-i','color=c=red@0.5:s=64x64','-frames:v','1','-vf','format=rgba',overlay)
        ff('-f','lavfi','-i','color=c=green@0.5:s=64x64','-frames:v','1','-vf','format=rgba',frame_two)
        still=import_clip(overlay)
        sequence=import_image_sequence([overlay,frame_two],fps=12)
        self.assertEqual(still.source_type,'image')
        self.assertEqual(sequence.source_type,'image_sequence')
        self.assertEqual(len(sequence.source_paths),2)
        base=replace(import_clip(self.blue),end=1,track=1)
        still=replace(still,position=0,track=2,opacity=.65)
        sequence=replace(sequence,position=5.1,track=2)
        tracks=[2,1,-1,-2]
        validate_timeline([base,still,sequence],tracks)
        target=self.root/'images-and-overlays.mp4';render([base,still,sequence],tracks,target,(160,90))
        self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')
        project=self.root/'images-and-overlays.framecut'
        save_project(project,[base,still,sequence],'720p · 16:9',tracks,[still,sequence],track_names={2:'Overlays'})
        loaded=load_project(project)
        self.assertEqual(loaded['clips'][1].source_type,'image')
        self.assertEqual(loaded['clips'][2].source_type,'image_sequence')
        self.assertEqual(loaded['track_names'],{2:'Overlays'})

    def test_subtitle_parsing_text_styles_animation_and_roundtrip(self):
        srt=self.root/'captions.srt'
        srt.write_text('''1\n00:00:00,100 --> 00:00:01,300\n<b>Hello</b> <i>Framecut</i>\n\n2\n00:00:01,500 --> 00:00:02,700\nSecond line\n''',encoding='utf-8')
        cues=parse_subtitle_file(srt)
        self.assertEqual(cues[0],{'start':.1,'end':1.3,'text':'Hello Framecut'})
        self.assertEqual(len(cues),2)
        vtt=self.root/'captions.vtt'
        vtt.write_text('''WEBVTT\n\n00:00.000 --> 00:00.800\nTop<br>cue\n''',encoding='utf-8')
        self.assertEqual(parse_subtitle_file(vtt)[0]['text'],'Top\ncue')
        video=replace(import_clip(self.blue),end=2,track=1)
        text=Clip('',864000,start=0,end=1.8,position=.1,track=2,kind='text',has_audio=False,text='Hello\nFramecut',source_type='text',
                  font_family='DejaVu Sans',font_bold=True,font_italic=True,outline_width=3,outline_color='#112233',
                  shadow_size=4,shadow_color='#223344',background_enabled=True,background_color='#445566',
                  background_opacity=.55,background_padding=20,text_animation='slide_left',text_animation_duration=.25,x=.5,y=.8)
        validate_timeline([video,text],self.tracks)
        target=self.root/'styled-subtitles.mp4';render([video,text],self.tracks,target,(320,180))
        self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')
        project=self.root/'styled-subtitles.framecut';save_project(project,[video,text],'720p · 16:9',self.tracks)
        loaded=load_project(project)['clips'][1]
        for field in ('font_family','font_bold','font_italic','outline_width','outline_color','shadow_size','shadow_color',
                      'background_enabled','background_color','background_opacity','background_padding','text_animation','text_animation_duration'):
            self.assertEqual(getattr(loaded,field),getattr(text,field))

    def test_step4_subtitle_export_srt_vtt_and_track_filter(self):
        video=replace(import_clip(self.blue),end=3,track=1)
        first=Clip('',864000,start=0,end=.9,position=.1,track=2,kind='text',has_audio=False,text='Hello\nWorld',source_type='text')
        second=Clip('',864000,start=0,end=1.2,position=1.4,track=2,kind='text',has_audio=False,text='Second cue',source_type='text')
        title=Clip('',864000,start=0,end=1,position=0,track=3,kind='text',has_audio=False,text='Not a subtitle',source_type='text')
        clips=[video,first,second,title]; tracks=[3,2,1,-1,-2]
        validate_timeline(clips,tracks)
        names={2:'Untertitel',3:'VIDEO 3'}
        cues=subtitle_cues_from_clips(clips,names)
        self.assertEqual([cue['text'] for cue in cues],['Hello\nWorld','Second cue'])
        srt=self.root/'exported.srt';vtt=self.root/'exported.vtt'
        write_subtitle_file(srt,clips,names);write_subtitle_file(vtt,clips,names)
        self.assertEqual(parse_subtitle_file(srt),cues);self.assertEqual(parse_subtitle_file(vtt),cues)
        self.assertIn('00:00:00,100 --> 00:00:01,000',srt.read_text())
        self.assertIn('00:00:00.100 --> 00:00:01.000',vtt.read_text())

    def test_video_transform_render_and_roundtrip(self):
        clip=replace(import_clip(self.red),end=.8,video_scale=1.35,video_x=.2,video_y=.7,
                     crop_left=.08,crop_top=.05,crop_right=.12,crop_bottom=.04,
                     rotation=17,flip_horizontal=True,brightness=.12,contrast=1.35,saturation=.42,
                     opacity=.62,blur=1.5,sharpen=.8)
        validate_timeline([clip],self.tracks)
        target=self.root/'transformed.mp4';render([clip],self.tracks,target,(320,180))
        self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')
        project=self.root/'transform.framecut';save_project(project,[clip],'720p · 16:9',self.tracks)
        loaded=load_project(project)['clips'][0]
        for field in ('video_scale','video_x','video_y','crop_left','crop_top','crop_right','crop_bottom','rotation','flip_horizontal','brightness','contrast','saturation','opacity','blur','sharpen'):
            self.assertEqual(getattr(loaded,field),getattr(clip,field))

    def test_keyframe_render_split_and_roundtrip(self):
        clip=replace(import_clip(self.blue),end=2,keyframes=[
            {'time':0,'scale':1.0,'x':.5,'y':.5,'rotation':0},
            {'time':1,'scale':1.5,'x':.25,'y':.7,'rotation':18},
            {'time':2,'scale':1.2,'x':.8,'y':.35,'rotation':-12},
        ])
        validate_timeline([clip],self.tracks)
        self.assertIn('if(lt', keyframe_expression(clip,'scale'))
        # Older transform-only keyframes remain valid after adding effect fields.
        target=self.root/'keyframes.mp4';render([clip],self.tracks,target,(320,180))
        self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')
        first,second=split_clip(clip,1)
        validate_timeline([first,second],self.tracks)
        self.assertAlmostEqual(first.keyframes[-1]['time'],first.length,places=5)
        self.assertAlmostEqual(second.keyframes[0]['time'],0,places=5)
        project=self.root/'keyframes.framecut';save_project(project,[clip],'720p · 16:9',self.tracks)
        loaded=load_project(project)['clips'][0]
        self.assertEqual(loaded.keyframes,clip.keyframes)

        effects=replace(clip,keyframes=[
            {'time':0,'scale':1.0,'x':.5,'y':.5,'rotation':0,'opacity':1.0,'blur':0.0},
            {'time':1,'scale':1.5,'x':.25,'y':.7,'rotation':18,'opacity':.35,'blur':2.5},
            {'time':2,'scale':1.2,'x':.8,'y':.35,'rotation':-12,'opacity':.8,'blur':.5},
        ])
        validate_timeline([effects],self.tracks)
        self.assertIn('if(lt', keyframe_expression(effects,'opacity'))
        self.assertIn('if(lt', keyframe_expression(effects,'blur'))
        effect_target=self.root/'effect-keyframes.mp4';render([effects],self.tracks,effect_target,(320,180))
        self.assertTrue(probe(effect_target)[1]);ff('-i',effect_target,'-f','null','-')
        effect_project=self.root/'effect-keyframes.framecut';save_project(effect_project,[effects],'720p · 16:9',self.tracks)
        self.assertEqual(load_project(effect_project)['clips'][0].keyframes,effects.keyframes)

    def test_volume_keyframe_render_split_and_roundtrip(self):
        clip=replace(import_clip(self.tone),end=2,volume=.25,volume_keyframes=[
            {'time':0,'volume':.1},
            {'time':1,'volume':.8},
            {'time':2,'volume':.35},
        ])
        validate_timeline([clip],self.tracks)
        self.assertIn('if(lt',volume_keyframe_expression(clip))
        target=self.root/'volume-keyframes.mp4';render([clip],self.tracks,target,(160,90))
        self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')
        def rms(start):
            vals=array('f');vals.frombytes(ff('-i',target,'-ss',start,'-t',.2,'-vn','-ac',1,'-f','f32le','-').stdout)
            return (sum(value*value for value in vals)/len(vals))**.5
        self.assertGreater(rms(1.4),rms(.1)*2)
        first,second=split_clip(clip,1)
        validate_timeline([first,second],self.tracks)
        self.assertAlmostEqual(first.volume_keyframes[-1]['time'],first.length,places=5)
        self.assertAlmostEqual(second.volume_keyframes[0]['time'],0,places=5)
        project=self.root/'volume-keyframes.framecut';save_project(project,[clip],'720p · 16:9',self.tracks)
        loaded=load_project(project)['clips'][0]
        self.assertEqual(loaded.volume_keyframes,clip.volume_keyframes)

    def test_step5_audio_processing_and_roundtrip(self):
        """Audio controls are serialized and applied by the real FFmpeg graph."""
        clip=replace(import_clip(self.tone),end=2,volume=.6,
                     audio_noise_reduction=8,audio_eq_low=3,audio_eq_mid=-2,audio_eq_high=4,
                     audio_compressor_enabled=True,audio_compressor_threshold=-20,
                     audio_compressor_ratio=5,audio_voice_isolation=.65,audio_channel_mode='mono',audio_pan=-.25)
        filters=audio_effect_filters(clip)
        self.assertTrue(any(value.startswith('afftdn=') for value in filters))
        self.assertTrue(any(value.startswith('pan=stereo|') for value in filters))
        self.assertTrue(any(value.startswith('highpass=') for value in filters))
        self.assertTrue(any(value.startswith('lowpass=') for value in filters))
        self.assertTrue(any(value.startswith('acompressor=') for value in filters))
        self.assertEqual(sum(value.startswith('equalizer=') for value in filters),3)
        self.assertTrue(any(value.startswith('acompressor=') for value in filters))
        self.assertIn('pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1',filters)
        self.assertIn('pan=stereo|c0=1.000000*c0|c1=0.750000*c1',filters)
        validate_timeline([clip],self.tracks)
        target=self.root/'step5-audio-processing.mp4';render([clip],self.tracks,target,(160,90))
        duration,video,audio=probe(target)
        self.assertTrue(video and audio);self.assertLess(abs(duration-2),.1)
        ff('-i',target,'-f','null','-')
        project=self.root/'step5-audio-processing.framecut'
        save_project(project,[clip],'720p · 16:9',self.tracks)
        loaded=load_project(project)['clips'][0]
        for field in ('audio_noise_reduction','audio_eq_low','audio_eq_mid','audio_eq_high',
                      'audio_compressor_enabled','audio_compressor_threshold','audio_compressor_ratio',
                      'audio_voice_isolation','audio_channel_mode','audio_pan'):
            self.assertEqual(getattr(loaded,field),getattr(clip,field))

    def test_step8_local_ai_video_tools_roundtrip_and_render(self):
        """Tracking, object fill and a transparent derivative reach the render graph."""
        tracked=replace(import_clip(self.blue),end=2,mask_type='rectangle',mask_x=.15,mask_y=.2,
                        mask_width=.35,mask_height=.4,mask_feather=.03,
                        tracking_keyframes=[
                            {'time':0,'x':.15,'y':.2,'width':.35,'height':.4,'score':.99},
                            {'time':1,'x':.25,'y':.24,'width':.35,'height':.4,'score':.94},
                            {'time':2,'x':.32,'y':.28,'width':.35,'height':.4,'score':.91},
                        ],object_removal_enabled=True)
        validate_timeline([tracked],self.tracks)
        self.assertIn('if(lt',tracking_expression(tracked,'x'))
        tracked_target=self.root/'step8-tracked-object.mp4';render([tracked],self.tracks,tracked_target,(320,180))
        self.assertTrue(probe(tracked_target)[1]);ff('-i',tracked_target,'-f','null','-')

        transparent=self.root/'step8-transparent.mov'
        ff('-f','lavfi','-i','color=c=red@0.5:s=320x180:r=30','-t',1,'-vf','format=rgba',
           '-c:v','qtrle','-pix_fmt','argb',transparent)
        background=replace(import_clip(self.blue),end=1,track=2,background_removal_enabled=True,
                           background_removed_path=str(transparent))
        validate_timeline([background],self.tracks)
        background_target=self.root/'step8-background.mp4';render([background],self.tracks,background_target,(320,180))
        self.assertTrue(probe(background_target)[1]);ff('-i',background_target,'-f','null','-')

        project=self.root/'step8-ai.framecut';save_project(project,[tracked,background],'720p · 16:9',self.tracks)
        loaded=load_project(project)['clips']
        self.assertEqual(loaded[0].tracking_keyframes,tracked.tracking_keyframes)
        self.assertTrue(loaded[0].object_removal_enabled)
        self.assertEqual(Path(loaded[1].background_removed_path),transparent.resolve())

    def test_step9_auto_reframe_render_split_and_roundtrip(self):
        """Auto-Reframe follows focus points in the real crop/render graph."""
        clip=replace(import_clip(self.blue),end=2,auto_reframe_enabled=True,
                     auto_reframe_format='9:16',auto_reframe_keyframes=[
                         {'time':0,'x':.25,'y':.5,'width':.3,'height':.3,'score':1.0,'curve':'ease_in_out'},
                         {'time':1,'x':.75,'y':.5,'width':.3,'height':.3,'score':.9,'curve':'ease_in_out'},
                         {'time':2,'x':.65,'y':.45,'width':.25,'height':.25,'score':0.0,'curve':'ease_in_out'},
                     ])
        validate_timeline([clip],self.tracks)
        self.assertAlmostEqual(auto_reframe_aspect('9:16',(320,180)),9/16)
        self.assertIn('if(lt',auto_reframe_expression(clip,'x'))
        target=self.root/'step9-auto-reframe.mp4';render([clip],self.tracks,target,(180,320))
        self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')
        first,second=split_clip(clip,1)
        validate_timeline([first,second],self.tracks)
        self.assertAlmostEqual(first.auto_reframe_keyframes[-1]['time'],first.length,places=5)
        self.assertAlmostEqual(second.auto_reframe_keyframes[0]['time'],0,places=5)
        project=self.root/'step9-auto-reframe.framecut';save_project(project,[clip],'1080p · 9:16',self.tracks)
        loaded=load_project(project)['clips'][0]
        self.assertTrue(loaded.auto_reframe_enabled)
        self.assertEqual(loaded.auto_reframe_format,clip.auto_reframe_format)
        self.assertEqual(loaded.auto_reframe_keyframes,clip.auto_reframe_keyframes)

    def test_step10_bezier_grading_and_beat_sync(self):
        """Free masks, three-way grading and beat markers survive delivery."""
        points=[{'x':.10,'y':.12},{'x':.62,'y':.08},{'x':.88,'y':.55},{'x':.46,'y':.90},{'x':.08,'y':.68}]
        moved=[{'x':.18,'y':.10},{'x':.72,'y':.14},{'x':.92,'y':.62},{'x':.50,'y':.94},{'x':.12,'y':.70}]
        clip=replace(import_clip(self.blue),end=2,mask_type='bezier',mask_points=points,mask_feather=.03,
                     mask_path_keyframes=[{'time':0,'points':points},{'time':1,'points':moved}],
                     color_exposure=.75,color_temperature=.35,color_tint=-.2,color_vibrance=.45,
                     color_lift_r=.12,color_lift_g=-.04,color_lift_b=.08,
                     color_gamma_r=-.10,color_gamma_g=.06,color_gamma_b=.14,
                     color_gain_r=.18,color_gain_g=.03,color_gain_b=-.08)
        validate_timeline([clip],self.tracks)
        self.assertTrue(any(value.startswith('colorbalance=') for value in color_grading_filters(clip)))
        target=self.root/'step10-bezier-grading.mp4';render([clip],self.tracks,target,(320,180))
        self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')
        first,second=split_clip(clip,1)
        validate_timeline([first,second],self.tracks)
        self.assertEqual(len(first.mask_path_keyframes),2)
        self.assertEqual(float(second.mask_path_keyframes[0]['time']),0.0)
        markers=[{'time':.25,'label':'Beat 1','kind':'beat'},{'time':.75,'label':'Beat 2','kind':'beat'}]
        project=self.root/'step10-delivery.framecut';save_project(project,[clip],'720p · 16:9',self.tracks,markers=markers)
        loaded=load_project(project)
        loaded_clip=loaded['clips'][0]
        self.assertEqual(loaded_clip.mask_points,clip.mask_points)
        self.assertEqual(loaded_clip.mask_path_keyframes,clip.mask_path_keyframes)
        self.assertEqual((loaded_clip.color_exposure,loaded_clip.color_gain_b),
                         (clip.color_exposure,clip.color_gain_b))
        self.assertEqual(loaded['markers'],normalize_markers(markers,loaded['clips'][0].finish))

        clicks=self.root/'step10-clicks.wav'
        ff('-f','lavfi','-i','aevalsrc=if(lt(mod(t\\,0.5)\\,0.03)\\,sin(2*PI*900*t)\\,0):s=22050',
           '-t',3,'-c:a','pcm_s16le',clicks)
        beat_data=analyze_beats(clicks,0,3)
        self.assertGreaterEqual(len(beat_data['beats']),4)
        self.assertGreater(beat_data['bpm'],100)

    def test_step5_audio_ducking_render(self):
        """A ducked music bed is lowered while the foreground voice is present."""
        music=replace(import_clip(self.tone),end=2,volume=.35,audio_ducking=.9,track=-1)
        voice=replace(import_clip(self.voice),position=.5,volume=.9,track=-2,uid='voice')
        tracks=[-1,-2]
        validate_timeline([music,voice],tracks)
        target=self.root/'step5-ducking.mp4';render([music,voice],tracks,target,(160,90))
        self.assertTrue(probe(target)[2]);ff('-i',target,'-f','null','-')
        def band_rms(start):
            values=array('f');values.frombytes(ff('-i',target,'-ss',start,'-t','0.2','-vn','-ac','1',
                                                   '-af','bandpass=frequency=440:width_type=h:width=80',
                                                   '-f','f32le','-').stdout)
            return (sum(value*value for value in values)/len(values))**.5
        outside=band_rms(.1);inside=band_rms(.7)
        self.assertGreater(outside,.01)
        self.assertLess(inside,outside*.75)

    def test_step5_audio_validation(self):
        clip=import_clip(self.tone)
        with self.assertRaisesRegex(ValueError,'Rauschunterdrückung'):
            validate_timeline([replace(clip,audio_noise_reduction=31)],self.tracks)
        with self.assertRaisesRegex(ValueError,'Kompressoreinstellung'):
            validate_timeline([replace(clip,audio_compressor_ratio=21)],self.tracks)
        with self.assertRaisesRegex(ValueError,'Kanalsteuerung'):
            validate_timeline([replace(clip,audio_channel_mode='surround')],self.tracks)

    def test_step6_export_profiles_fps_formats_bitrate_and_hdr(self):
        """FPS, bitrate, containers, codecs and HDR reach FFmpeg output metadata."""
        clip=replace(import_clip(self.red),end=.75,track=1)

        mp4_settings={'format':'mp4','video_codec':'h264','fps':60,'bitrate_kbps':2400,'encoder':'software','hdr':False}
        self.assertEqual(normalize_export_settings(mp4_settings)['bitrate_kbps'],2400)
        mp4=self.root/'step6-60fps.mp4';render([clip],self.tracks,mp4,(160,90),export_settings=mp4_settings)
        mp4_data=json.loads(subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(mp4)],
                                           check=True,capture_output=True,text=True).stdout)
        mp4_video=next(stream for stream in mp4_data['streams'] if stream['codec_type']=='video')
        self.assertEqual(mp4_video['codec_name'],'h264');self.assertEqual(mp4_video['r_frame_rate'],'60/1')
        self.assertIn('mp4',mp4_data['format']['format_name']);self.assertGreater(int(mp4_video.get('bit_rate') or 0),0)

        hdr_settings={'format':'mkv','video_codec':'hevc','fps':50,'bitrate_kbps':2200,'encoder':'software','hdr':True}
        mkv=self.root/'step6-hdr.mkv';render([clip],self.tracks,mkv,(160,90),export_settings=hdr_settings)
        mkv_data=json.loads(subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(mkv)],
                                           check=True,capture_output=True,text=True).stdout)
        mkv_video=next(stream for stream in mkv_data['streams'] if stream['codec_type']=='video')
        self.assertIn('matroska',mkv_data['format']['format_name']);self.assertEqual(mkv_video['codec_name'],'hevc')
        self.assertEqual(mkv_video['pix_fmt'],'yuv420p10le');self.assertEqual(mkv_video['color_transfer'],'smpte2084')
        self.assertEqual(mkv_video['color_primaries'],'bt2020');self.assertEqual(mkv_video['r_frame_rate'],'50/1')

        webm_settings={'format':'webm','video_codec':'vp9','fps':25,'bitrate_kbps':1800,'encoder':'software','hdr':False}
        webm=self.root/'step6-webm.webm';render([clip],self.tracks,webm,(160,90),export_settings=webm_settings)
        webm_data=json.loads(subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(webm)],
                                            check=True,capture_output=True,text=True).stdout)
        webm_video=next(stream for stream in webm_data['streams'] if stream['codec_type']=='video')
        webm_audio=next(stream for stream in webm_data['streams'] if stream['codec_type']=='audio')
        self.assertIn('webm',webm_data['format']['format_name']);self.assertEqual(webm_video['codec_name'],'vp9')
        self.assertEqual(webm_audio['codec_name'],'opus');self.assertEqual(webm_video['r_frame_rate'],'25/1')

        with self.assertRaisesRegex(ValueError,'HDR benötigt'):
            normalize_export_settings({'format':'mp4','video_codec':'h264','fps':30,'bitrate_kbps':1200,'encoder':'software','hdr':True})
        self.assertEqual(resolve_export_encoder(normalize_export_settings({'format':'mp4','video_codec':'h264','fps':30,
                                                                             'bitrate_kbps':1200,'encoder':'software','hdr':False}))[0],'software')

    def test_transition_render_and_adjacency_validation(self):
        first=replace(import_clip(self.blue),end=1,position=0)
        second=replace(import_clip(self.red),end=.8,position=1,transition_type='dissolve',transition_duration=.25)
        validate_timeline([first,second],self.tracks)
        target=self.root/'transition.mp4';render([first,second],self.tracks,target,(320,180))
        self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')
        with self.assertRaisesRegex(ValueError,'direkt angrenzenden'):
            validate_timeline([first,replace(second,position=2)],self.tracks)
        project=self.root/'transition.framecut';save_project(project,[first,second],'720p · 16:9',self.tracks)
        self.assertEqual(load_project(project)['clips'][1].transition_type,'dissolve')

    def test_step4_transition_variants_render(self):
        """Every new transition is a real render path, not only a UI value."""
        kinds=('slide_left','slide_right','slide_up','slide_down',
               'wipe_left','wipe_right','wipe_up','wipe_down','zoom','dip_to_black')
        for kind in kinds:
            with self.subTest(transition=kind):
                first=replace(import_clip(self.blue),end=1,position=0,track=1)
                second=replace(import_clip(self.red),end=.8,position=1,track=1,
                               transition_type=kind,transition_duration=.25)
                validate_timeline([first,second],self.tracks)
                target=self.root/f'transition-{kind}.mp4'
                render([first,second],self.tracks,target,(320,180))
                self.assertTrue(probe(target)[1])
                ff('-i',target,'-f','null','-')

    def test_step4_effects_speed_ramp_freeze_reverse_lut_mask_and_roundtrip(self):
        lut=self.root/'identity.cube'
        lut.write_text('''TITLE "Identity"\nLUT_3D_SIZE 2\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n0 0 0\n0 0 1\n0 1 0\n0 1 1\n1 0 0\n1 0 1\n1 1 0\n1 1 1\n''',encoding='utf-8')
        clip=replace(import_clip(self.blue),end=2,reverse=True,freeze_frame=True,freeze_duration=.35,
                     speed=.85,speed_keyframes=[{'time':0,'speed':.75},{'time':.8,'speed':1.5},{'time':1.6,'speed':.5}],
                     filter_preset='cinematic',lut_path=str(lut),chroma_key_enabled=True,
                     chroma_key_color='#00ff00',chroma_key_similarity=.15,chroma_key_blend=.2,
                     mask_type='ellipse',mask_x=.08,mask_y=.08,mask_width=.84,mask_height=.84,mask_feather=.08,
                     opacity=.82)
        validate_timeline([clip],self.tracks)
        self.assertIn('if(lt',speed_keyframe_expression(clip))
        self.assertGreater(speed_ramp_duration(clip.end-clip.start,clip.speed,clip.speed_keyframes),0)
        self.assertGreater(clip.length,clip.end-clip.start)
        target=self.root/'step4-effects.mp4';render([clip],self.tracks,target,(320,180))
        self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')
        project=self.root/'step4-effects.framecut'
        save_project(project,[clip],'720p · 16:9',self.tracks)
        loaded=load_project(project)['clips'][0]
        for field in ('speed_keyframes','freeze_frame','freeze_duration','reverse','filter_preset','chroma_key_enabled',
                      'chroma_key_color','chroma_key_similarity','chroma_key_blend','mask_type','mask_x','mask_y',
                      'mask_width','mask_height','mask_feather','opacity'):
            self.assertEqual(getattr(loaded,field),getattr(clip,field))
        self.assertEqual(Path(loaded.lut_path),lut.resolve())

    def test_step4_effect_validation(self):
        clip=import_clip(self.blue)
        with self.assertRaisesRegex(ValueError,'Speed-Ramping-Zeit'):
            validate_timeline([replace(clip,speed_keyframes=[{'time':.5,'speed':1},{'time':.2,'speed':2}])],self.tracks)
        with self.assertRaisesRegex(ValueError,'Maske'):
            validate_timeline([replace(clip,mask_type='ellipse',mask_x=.8,mask_width=.4)],self.tracks)
        with self.assertRaisesRegex(ValueError,'Übergang'):
            validate_timeline([replace(clip,transition_type='does_not_exist')],self.tracks)

    def test_step5_effect_animation_system_adjustment_stabilization_and_transitions(self):
        """The new effect stack survives roundtrip and produces decodable video."""
        self.assertEqual(set(EFFECT_PRESETS),{'clean','cinematic','dream','noir','vivid','soft_focus'})
        self.assertTrue({'fade_white','blur_in','circle_open','circle_close','radial','pixelize',
                         'smooth_left','cover_right'}.issubset(TRANSITION_TYPES))
        self.assertEqual(curve_progress(.5,'ease_in'),.25)
        self.assertAlmostEqual(curve_progress(.5,'ease_out'),.75)
        self.assertEqual(set(KEYFRAME_CURVES),{'linear','ease_in','ease_out','ease_in_out'})
        animated=replace(import_clip(self.blue),end=2,track=1,brightness=.08,contrast=1.12,
                         effect_preset='cinematic',stabilization=.45,
                         keyframes=[{'time':0,'scale':1,'x':.5,'y':.5,'rotation':0,'curve':'ease_in'},
                                    {'time':1.4,'scale':1.5,'x':.7,'y':.4,'rotation':15,'opacity':.7,'blur':1.2,'curve':'ease_out'}],
                         volume_keyframes=[])
        validate_timeline([animated],self.tracks)
        self.assertIn('pow',keyframe_expression(animated,'scale'))
        adjustment=Clip('',864000,start=0,end=2,position=0,track=2,kind='video',has_audio=False,
                        source_type='adjustment',effect_preset='dream',brightness=.04,blur=.25)
        validate_timeline([animated,adjustment],self.tracks)
        output=self.root/'step5-adjustment-stabilized.mp4'
        render([animated,adjustment],self.tracks,output,(320,180))
        self.assertTrue(probe(output)[1]);ff('-i',output,'-f','null','-')
        project=self.root/'step5-effects.framecut'
        save_project(project,[animated,adjustment],'720p · 16:9',self.tracks,[animated])
        loaded=load_project(project)
        loaded_adjustment=next(value for value in loaded['clips'] if value.source_type=='adjustment')
        loaded_animated=next(value for value in loaded['clips'] if value.source_type!='adjustment')
        self.assertEqual(loaded_adjustment.path,'')
        self.assertEqual(loaded_adjustment.effect_preset,'dream')
        self.assertEqual(loaded_animated.keyframes[0]['curve'],'ease_in')
        self.assertEqual(loaded_animated.effect_preset,'cinematic')
        for kind in ('fade_white','blur_in','circle_open','circle_close','radial','pixelize','smooth_left','cover_right'):
            with self.subTest(transition=kind):
                first=replace(import_clip(self.blue),end=1,position=0,track=1)
                second=replace(import_clip(self.red),end=.8,position=1,track=1,transition_type=kind,transition_duration=.25)
                validate_timeline([first,second],self.tracks)
                target=self.root/f'step5-transition-{kind}.mp4'
                render([first,second],self.tracks,target,(320,180))
                self.assertTrue(probe(target)[1]);ff('-i',target,'-f','null','-')

    def test_step4_speed_ramp_split_preserves_timing(self):
        clip=replace(import_clip(self.blue),end=2,speed=.75,
                     speed_keyframes=[{'time':0,'speed':.5},{'time':.75,'speed':2.0},{'time':1.5,'speed':.75}])
        split_time=clip.position+clip.length/2
        first,second=split_clip(clip,split_time)
        validate_timeline([first,second],self.tracks)
        self.assertAlmostEqual(first.finish,second.position,places=5)
        self.assertAlmostEqual(first.length+second.length,clip.length,places=4)
        self.assertAlmostEqual(first.end,second.start,places=5)

    def test_step4_reverse_preserves_video_and_audio_streams(self):
        clip=replace(import_clip(self.red),end=.8,reverse=True,speed=1.5)
        target=self.root/'reverse.mp4';render([clip],self.tracks,target,(320,180))
        duration,video,audio=probe(target)
        self.assertTrue(video and audio);self.assertLess(abs(duration-clip.length),.1)
        ff('-i',target,'-f','null','-')

    def test_cancellation_and_source_protection(self):
        clip=import_clip(self.blue);target=self.root/'existing.mp4';target.write_bytes(b'keep-me')
        cancel=threading.Event();cancel.set()
        with self.assertRaises(ExportCancelled):render([clip],self.tracks,target,(320,180),cancel=cancel)
        self.assertEqual(target.read_bytes(),b'keep-me')
        with self.assertRaises(ValueError):render([clip],self.tracks,self.blue)
        with self.assertRaises(ValueError):save_project(self.blue,[clip],next(iter({'a':1})),self.tracks)
        self.assertTrue(probe(self.blue)[1])
        # Cancel while FFmpeg is running, not only before startup.
        cancel.clear();timer=threading.Timer(.25,cancel.set);timer.start()
        try:
            many=[replace(clip,position=i*3,uid=f'id{i}') for i in range(6)]
            with self.assertRaises(ExportCancelled):render(many,self.tracks,target,(1920,1080),cancel=cancel)
        finally:timer.cancel()
        self.assertEqual(target.read_bytes(),b'keep-me')
        self.assertFalse(list(self.root.glob('.framecut-render-*')))


if __name__=='__main__':unittest.main()
