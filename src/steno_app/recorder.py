# recorder.py
import sys
import os
import objc
import logging
from Foundation import NSObject, NSLog
from AVFoundation import (
    AVAssetWriter, AVAssetWriterInput, AVMediaTypeVideo, AVMediaTypeAudio,
    AVFileTypeMPEG4, AVFileTypeAppleM4A, # <--- Добавили тип M4A
    AVVideoCodecKey, AVVideoWidthKey, AVVideoHeightKey,
    AVVideoCompressionPropertiesKey, AVVideoAverageBitRateKey, AVVideoProfileLevelKey,
    AVVideoH264EntropyModeKey, AVVideoH264EntropyModeCABAC,
    AVFormatIDKey, AVNumberOfChannelsKey, AVSampleRateKey, AVEncoderBitRateKey,
    AVCaptureSession, AVCaptureDevice, AVCaptureDeviceInput, AVCaptureAudioDataOutput,
    AVCaptureConnection, AVVideoCodecTypeH264,
    AVAssetWriterInputPixelBufferAdaptor
)
import CoreMedia
import Quartz
import ScreenCaptureKit as SCK

# --- Настройка логгера ---
logger = logging.getLogger("RecorderCore")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s [Recorder] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

STREAM_SIGNATURE = b'v@:@@q' 

class ScreenRecorder(NSObject):
    
    # Изменили сигнатуру: теперь принимаем main_url (Video+SysAudio) и aux_url (MicAudio)
    def initWithOutputURLs_auxURL_videoConfig_(self, main_url, aux_url, config):
        self = objc.super(ScreenRecorder, self).init()
        if self is None: return None
        
        self.main_url = main_url
        self.aux_url = aux_url
        self.width = int(config.get("width", 1280))
        self.height = int(config.get("height", 720))
        self.fps = int(config.get("fps", 10))
        self.bitrate = int(config.get("bitrate", 3000000))
        
        # --- WRITER 1: Main (Video + System Audio) ---
        self.main_writer = None
        self.video_input = None
        self.video_adaptor = None
        self.sys_input = None
        
        # --- WRITER 2: Aux (Mic Audio Only) ---
        self.aux_writer = None
        self.mic_input = None
        
        # --- Inputs & Sessions ---
        self.stream = None
        self.mic_session = None
        self.mic_queue = None
        self.video_queue = None
        
        self.is_recording = False
        
        # Флаги старта сессий (они теперь независимы)
        self.main_session_started = False 
        self.aux_session_started = False
        
        # --- Cleanup Files ---
        for url in [main_url, aux_url]:
            path = url.path()
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    logger.error(f"Cannot remove existing file: {path}")

        # ==========================================
        # 1. Setup Main Writer (Video + Sys Audio) -> .mp4
        # ==========================================
        err_main = None
        self.main_writer, err_main = AVAssetWriter.alloc().initWithURL_fileType_error_(
            main_url, AVFileTypeMPEG4, None
        )
        if err_main:
            logger.error(f"Error creating Main Writer: {err_main}")
            return None
            
        # Video Settings
        compression_props = {
            AVVideoAverageBitRateKey: self.bitrate,
            AVVideoProfileLevelKey: "H264_Main_AutoLevel",
            AVVideoH264EntropyModeKey: AVVideoH264EntropyModeCABAC,
            "AllowFrameReordering": False
        }
        video_settings = {
            AVVideoCodecKey: AVVideoCodecTypeH264,
            AVVideoWidthKey: self.width,
            AVVideoHeightKey: self.height,
            AVVideoCompressionPropertiesKey: compression_props
        }
        self.video_input = AVAssetWriterInput.assetWriterInputWithMediaType_outputSettings_(
            AVMediaTypeVideo, video_settings
        )
        self.video_input.setExpectsMediaDataInRealTime_(True)
        self.video_adaptor = AVAssetWriterInputPixelBufferAdaptor.assetWriterInputPixelBufferAdaptorWithAssetWriterInput_sourcePixelBufferAttributes_(
            self.video_input, None
        )
        
        # Audio Settings (Common)
        audio_settings = {
            AVFormatIDKey: 1633772320, # kAudioFormatMPEG4AAC
            AVNumberOfChannelsKey: 2,
            AVSampleRateKey: 44100.0,
            AVEncoderBitRateKey: 128000,
        }
        
        # System Audio Input for Main Writer
        self.sys_input = AVAssetWriterInput.assetWriterInputWithMediaType_outputSettings_(
            AVMediaTypeAudio, audio_settings
        )
        self.sys_input.setExpectsMediaDataInRealTime_(True)
        
        if self.main_writer.canAddInput_(self.video_input): self.main_writer.addInput_(self.video_input)
        if self.main_writer.canAddInput_(self.sys_input): self.main_writer.addInput_(self.sys_input)

        # ==========================================
        # 2. Setup Aux Writer (Mic Audio) -> .m4a
        # ==========================================
        err_aux = None
        self.aux_writer, err_aux = AVAssetWriter.alloc().initWithURL_fileType_error_(
            aux_url, AVFileTypeAppleM4A, None # Используем контейнер M4A для аудио
        )
        if err_aux:
             logger.error(f"Error creating Aux Audio Writer: {err_aux}")
             return None

        # Mic Input for Aux Writer
        self.mic_input = AVAssetWriterInput.assetWriterInputWithMediaType_outputSettings_(
            AVMediaTypeAudio, audio_settings
        )
        self.mic_input.setExpectsMediaDataInRealTime_(True)
        
        if self.aux_writer.canAddInput_(self.mic_input): self.aux_writer.addInput_(self.mic_input)

        return self

    def startWithCallback_(self, callback):
        self.start_callback = callback
        logger.info("ScreenRecorder: Requesting content...")
        SCK.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
            False, True, self.handle_content_
        )

    def handle_content_(self, content, error):
        if error:
            logger.error(f"Error getting content: {error}")
            if hasattr(self, 'start_callback') and self.start_callback:
                self.start_callback(False, str(error))
            return

        displays = content.displays()
        if not displays:
            logger.error("No displays found")
            if hasattr(self, 'start_callback') and self.start_callback:
                self.start_callback(False, "No displays found")
            return
        
        # --- Микрофон (AVCapture) ---
        self.mic_session = AVCaptureSession.alloc().init()
        mic_device = AVCaptureDevice.defaultDeviceWithMediaType_(AVMediaTypeAudio)
        
        if mic_device:
            mic_inp, err = AVCaptureDeviceInput.deviceInputWithDevice_error_(mic_device, None)
            if not err and self.mic_session.canAddInput_(mic_inp):
                self.mic_session.addInput_(mic_inp)
            
            try:
                import dispatch
                self.mic_queue = dispatch.dispatch_queue_create(b"mic_queue", dispatch.DISPATCH_QUEUE_SERIAL)
            except: pass

            mic_out = AVCaptureAudioDataOutput.alloc().init()
            mic_out.setSampleBufferDelegate_queue_(self, self.mic_queue if self.mic_queue else None)
            if self.mic_session.canAddOutput_(mic_out):
                self.mic_session.addOutput_(mic_out)
            
            self.mic_session.startRunning()

        # --- Экран + Sys Audio (SCK) ---
        display = displays[0]
        config = SCK.SCStreamConfiguration.alloc().init()
        config.setWidth_(self.width)
        config.setHeight_(self.height)
        config.setPixelFormat_(Quartz.kCVPixelFormatType_32BGRA)
        config.setCapturesAudio_(True)
        config.setMinimumFrameInterval_(CoreMedia.CMTimeMake(1, self.fps))
        config.setQueueDepth_(6)

        filter_ = SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display, [])
        self.stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(filter_, config, self)
        
        try:
            import dispatch
            self.video_queue = dispatch.dispatch_queue_create(b"video_queue", dispatch.DISPATCH_QUEUE_SERIAL)
        except:
            self.video_queue = None

        # 0=Video, 1=Audio
        self.stream.addStreamOutput_type_sampleHandlerQueue_error_(self, 0, self.video_queue, None)
        self.stream.addStreamOutput_type_sampleHandlerQueue_error_(self, 1, self.video_queue, None)
        
        # Стартуем обоих писателей
        if self.main_writer.startWriting() and self.aux_writer.startWriting():
            self.is_recording = True
            logger.info("Both writers initialized. Waiting for data...")
            
            def stream_handler(err):
                if err:
                    logger.error(f"Stream error: {err}")
                    if hasattr(self, 'start_callback') and self.start_callback:
                        self.start_callback(False, str(err))
                else:
                    logger.info("Stream started")
                    if hasattr(self, 'start_callback') and self.start_callback:
                        self.start_callback(True, None)

            self.stream.startCaptureWithCompletionHandler_(stream_handler)
        else:
            logger.error("Failed to start one of the writers")
            if hasattr(self, 'start_callback') and self.start_callback:
                self.start_callback(False, "Failed to start one of the writers")

    def stop(self):
        logger.info("ScreenRecorder: stop called")
        self.is_recording = False
        
        if self.stream: self.stream.stopCaptureWithCompletionHandler_(lambda e: None)
        if self.mic_session: self.mic_session.stopRunning()
            
        # Маркируем инпуты как finished
        if self.video_input: self.video_input.markAsFinished()
        if self.mic_input: self.mic_input.markAsFinished()
        if self.sys_input: self.sys_input.markAsFinished()
        
        # Закрываем Main Writer
        if self.main_writer:
            self.main_writer.finishWritingWithCompletionHandler_(lambda: logger.info("Main Writer finished"))
            
        # Закрываем Aux Writer
        if self.aux_writer:
            self.aux_writer.finishWritingWithCompletionHandler_(lambda: logger.info("Aux Audio Writer finished"))

    # --- Delegates ---

    @objc.typedSelector(STREAM_SIGNATURE)
    def stream_didOutputSampleBuffer_ofType_(self, stream, sampleBuffer, outputType):
        if not self.is_recording: return
        
        with objc.autorelease_pool():
            if not CoreMedia.CMSampleBufferDataIsReady(sampleBuffer): return
            
            pts = CoreMedia.CMSampleBufferGetPresentationTimeStamp(sampleBuffer)

            # --- VIDEO HANDLER (Main Writer) ---
            if outputType == 0: 
                # Логика старта Главной сессии (строго по Видео)
                if not self.main_session_started:
                    self.main_writer.startSessionAtSourceTime_(pts)
                    self.main_session_started = True
                    logger.info(f"Main Session started (Video PTS): {pts.value}")

                if self.video_input.isReadyForMoreMediaData():
                    pixel_buffer = CoreMedia.CMSampleBufferGetImageBuffer(sampleBuffer)
                    if pixel_buffer:
                        self.video_adaptor.appendPixelBuffer_withPresentationTime_(pixel_buffer, pts)

            # --- SYSTEM AUDIO HANDLER (Main Writer) ---
            elif outputType == 1:
                # Системный звук пишем в Main Writer, поэтому ждем, пока видео стартанет сессию
                if not self.main_session_started: return
                
                if self.sys_input.isReadyForMoreMediaData():
                    self.sys_input.appendSampleBuffer_(sampleBuffer)

    # --- MICROPHONE HANDLER (Aux Writer) ---
    def captureOutput_didOutputSampleBuffer_fromConnection_(self, output, sampleBuffer, connection):
        if not self.is_recording: return
        
        with objc.autorelease_pool():
            if not CoreMedia.CMSampleBufferDataIsReady(sampleBuffer): return
            
            # Логика старта Aux сессии (независимо от видео)
            if not self.aux_session_started:
                pts = CoreMedia.CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
                self.aux_writer.startSessionAtSourceTime_(pts)
                self.aux_session_started = True
                logger.info(f"Aux Audio Session started (Mic PTS): {pts.value}")
            
            if self.mic_input.isReadyForMoreMediaData():
                self.mic_input.appendSampleBuffer_(sampleBuffer)