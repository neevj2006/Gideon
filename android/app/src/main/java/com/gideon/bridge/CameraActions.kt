package com.gideon.bridge

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.*
import android.media.ImageReader
import android.media.MediaRecorder
import android.os.Handler
import android.os.HandlerThread
import android.provider.MediaStore
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Saves photos and silent video to the app's media directories. */
class CameraActions(private val context: Context) {
    private val manager = context.getSystemService(CameraManager::class.java)
    private val worker = HandlerThread("GideonCamera").apply { start() }
    private val handler = Handler(worker.looper)
    private var videoDevice: CameraDevice? = null
    private var videoSession: CameraCaptureSession? = null
    private var recorder: MediaRecorder? = null

    fun flashlight(enabled: Boolean) {
        val id = manager.cameraIdList.firstOrNull { manager.getCameraCharacteristics(it).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true }
            ?: throw IllegalStateException("No flashlight is available")
        manager.setTorchMode(id, enabled)
    }

    private fun cameraId(side: String): String {
        val facing = if (side == "front") CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
        return manager.cameraIdList.firstOrNull { manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == facing }
            ?: throw IllegalStateException("Requested camera is unavailable")
    }

    @SuppressLint("MissingPermission")
    private fun open(id: String, callback: (CameraDevice) -> Unit) {
        manager.openCamera(id, object : CameraDevice.StateCallback() {
            override fun onOpened(camera: CameraDevice) = callback(camera)
            override fun onDisconnected(camera: CameraDevice) = camera.close()
            override fun onError(camera: CameraDevice, error: Int) { camera.close() }
        }, handler)
    }

    fun photo(side: String) {
        val reader = ImageReader.newInstance(1280, 720, ImageFormat.JPEG, 2)
        reader.setOnImageAvailableListener({ source ->
            source.acquireLatestImage()?.use { image ->
                val buffer = image.planes[0].buffer; val bytes = ByteArray(buffer.remaining()); buffer.get(bytes)
                val dir = File(context.getExternalFilesDir(null), "Pictures").apply { mkdirs() }
                File(dir, "gideon-${System.currentTimeMillis()}.jpg").writeBytes(bytes)
            }
        }, handler)
        open(cameraId(side)) { camera ->
            camera.createCaptureSession(listOf(reader.surface), object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(session: CameraCaptureSession) {
                    val request = camera.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                        addTarget(reader.surface); set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                    }.build()
                    session.capture(request, object : CameraCaptureSession.CaptureCallback() {
                        override fun onCaptureCompleted(s: CameraCaptureSession, r: CaptureRequest, result: TotalCaptureResult) { s.close(); camera.close(); reader.close() }
                    }, handler)
                }
                override fun onConfigureFailed(session: CameraCaptureSession) { camera.close(); reader.close() }
            }, handler)
        }
    }

    @Suppress("DEPRECATION")
    fun startVideo(side: String) {
        if (recorder != null) throw IllegalStateException("Video is already recording")
        val output = File(File(context.getExternalFilesDir(null), "Movies").apply { mkdirs() }, "gideon-${System.currentTimeMillis()}.mp4")
        val mediaRecorder = MediaRecorder().apply {
            setVideoSource(MediaRecorder.VideoSource.SURFACE)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setOutputFile(output.absolutePath)
            setVideoEncoder(MediaRecorder.VideoEncoder.H264)
            setVideoEncodingBitRate(4_000_000); setVideoFrameRate(30); setVideoSize(1280, 720)
            prepare()
        }
        recorder = mediaRecorder
        open(cameraId(side)) { camera ->
            videoDevice = camera
            camera.createCaptureSession(listOf(mediaRecorder.surface), object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(session: CameraCaptureSession) {
                    videoSession = session
                    val request = camera.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply { addTarget(mediaRecorder.surface) }.build()
                    session.setRepeatingRequest(request, null, handler); mediaRecorder.start()
                }
                override fun onConfigureFailed(session: CameraCaptureSession) { stopVideo() }
            }, handler)
        }
    }

    fun stopVideo() {
        try { recorder?.stop() } catch (_: RuntimeException) { }
        recorder?.reset(); recorder?.release(); recorder = null
        videoSession?.close(); videoSession = null; videoDevice?.close(); videoDevice = null
    }
}
