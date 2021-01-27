# HTTPImageServer
A naive http-based tool to show the image in a given directory. 

## 1. Dependency
- python3
- Pillow
> Install pillow via ```pip install pillow```

## 2. How to use
A simple command would do the job:
```shell
python server.py <port> <webroot>
```
where ```port``` is a int number of which port to use (default: 80), and ```webroot``` is the directory that containing the images(default: current directory).

## 3. Mostly asked problem

Q1. ```KeyError: webp```

Ans. We use webp format to encode the image and your system have no libwebp installed. 

1. you can change the format to others by modifying the code ```img = img.save(img_stream, format='webp')``` in server.py/HTTPImageServer.handle_image(line 165)

2. you can install ```libwebp-dev``` and reinstall pillow package for webp support.

## 3. Structure.
The server.py mainly provides two api.
1. To access filelist under the given directory, please access:
```
/directory?path=relative/path/to/file
```
params: 
    path: the directory that you want to list.
return:
    ```json
    {
        "dirs": [list, of, subdirs],
        "imgs": [image, file, under, the, directory],
    }
    ```

2. to access the image:
```
/img?path=relative/path/to/file&height=100&width=200
```
params: 
    path: the image that you want to access.
    height: image max height.
    width: image max width.
    > Note: if no height and width are provided, the original image will be returned.
return:
    the image stream.

For more details about the structure, please see the network.py.

## 4. Ps

1. The http server are written starting from socket, i do not use the http.server module in python. Therefore, there might be some bugs and may cause some problems, be sure not to use in production enviroment.
2. The index.html is gabbage, i have never write javascript before. You can try to re-write it if you are disgusting with that.