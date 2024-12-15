# Performance Testing

Hardware:
```
GPU0: Nvidia GTX 1660 
GPU1: Nvidia RTX 3090
```

Test data: 6 audio files, 10 minutes long, roughly half speech


## Diarization

- server parallel: `GPU_PARALLEL_COUNTS=1`
  - `1,2` - `1` one for first GPU, `2` for second GPU 
- client parallel: `VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT=1`

### Server: GPU0 parallel=1, Client: parallel=1

- Startup: model loaded
- Duration: 23:13:05,253 to 23:15:32,217 ~= 2m27s
- Times: 24, 24, 24, 24, 24, 24

That's 3x longer than GPU1

### Server: GPU1 parallel=1, Client: parallel=1

- Startup: model loaded
- Duration: 22:52:18,360 to 22:53:07,058 ~= 49s 
- Times: 8, 8, 8, 8, 7, 8

### Server: GPU1 parallel=1, Client: parallel=2

- Startup: model loaded
- Duration: 22:55:56,977 to 22:56:43,264 ~= 47s
- Times: 8, 15, 15, 15, 15, 14

### Server: GPU1 parallel=2, Client: parallel=2

- Startup: model loaded
- Duration: 23:28:45,099 to 23:29:25,946 ~= 40s
- Times: 14, 14, 13, 13, 13, 13

### Server: GPU0 GPU1 parallel=1, Client: parallel=2, 6 files

- Startup: model loaded
- Duration: 23:34:31,768 to 23:35:22,795 ~= 49s
- Times: 9, 8, 8, 26, 8, 24

We were waiting for the slow GPU to finish, so that slowed it down a lot

### Server: GPU0 GPU1 parallel=1, Client: parallel=2, 20 files

- Startup: model loaded
- Duration: 23:43:52,589 to 23:46:04,300 ~= 2m12s * (6/20) ~= 39,6s
- Times: 8,8,8,259,8,8,259,8,259,9,8,25,9,8,8,25,8

Adding slow GPU makes sense only with a lot of files

---------------------------------------------------------------------------------------

Using `1` parallel count on slow GPU and `2` on fast will probably get the best results.

Near 100% GPU use with this hardware can be reached with following settings:

- Pyannote Server
    ```
    environment:
      - GPU_PARALLEL_COUNTS=2,1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['1', '0']
              capabilities: [gpu]
    ```
  
- Client
    ```
    # this is one more than GPUs can handle, to allow server to preprocess the next audio while it's waiting
    VIDEO_PYANNOTE_DIARIZE_PARALLEL_COUNT=4
    ```


## Transcription

- server parallel: `WHISPER__DEVICE_INDEX=[0,1]` 
  - `[0,1]` on two gpu
  - `[0,0]` twice on same gpu
- client parallel: `WHISPER_PARALLEL_COUNTS=1`
  - `1,2` - `1` one for first server, `2` for second server 

### (outdated) Server: GPU0, Client: parallel=1

- Duration: 23:58:23,123 to 00:14:23,188 ~= 16m 
- Times: 161, 159, 159, 160, 160, 159

That's 10x longer than GPU1... Thankfully, the audio chunks are small, so it will not stop GPU1 from doing most of the work when used together. 

### (outdated) Server: GPU1, Client: parallel=1

- Startup: model loaded
- Duration: 00:36:55,159 to 00:38:30,617 ~= 1m35s
- Times: 15, 16, 15, 15, 15, 16

### (outdated) Server: GPU1, Client: parallel=2

- Startup: model loaded
- Duration: 00:26:15,354 to 00:27:45,031 ~= 1m30s
- Times: 14, 14, 14, 16, 14, 14

A tiny bit faster, maybe because of some pre-processing? Larger parallel on client has no effect.

### (outdated) Server: GPU1 parallel=2, Client: parallel=1

- Startup: model loaded
- Duration: 00:44:07,866 to 00:45:49,883 ~= 1m42s
- Times: 16, 17, 17, 16, 16, 16

**Slower! Don't load Whisper twice on one GPU!**

### Server: GPU0 GPU1, Client: parallel=2

Error: Cannot use multiple GPUs with different Compute Capabilities for the same model

---------------------------------------------------------------------------------------

### Server: GPU0 GPU1, Client: parallel=0,1, two servers, 3h40m audio

506 seconds

### Server: GPU0 GPU1, Client: parallel=1,1, two servers, 3h40m audio

472 seconds

### Server: GPU0 GPU1, Client: parallel=1,2, two servers, 3h40m audio

396 seconds

### Server: GPU0 GPU1, Client: parallel=2,2, two servers, 3h40m audio

410 seconds

### Server: GPU0 GPU1, Client: parallel=1,3, two servers, 3h40m audio

**385 seconds**
