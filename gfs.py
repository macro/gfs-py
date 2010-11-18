import math
import uuid
import os
import time
import operator

class GFSClient:
    def __init__(self, master):
        self.master = master

    def write(self, filename, data): # filename is full namespace path
        if self.exists(filename): # if already exists, overwrite
            self.delete(filename)
        num_chunks = self.num_chunks(len(data))
        chunkuuids = self.master.alloc(filename, num_chunks)
        self.write_chunks(chunkuuids, data)

    def write_chunks(self, chunkuuids, data):
        chunks = [ data[x:x+self.master.chunksize] \
            for x in range(0, len(data), self.master.chunksize) ]
        chunkservers = self.master.get_chunkservers()
        for i in range(0, len(chunkuuids)): # write to each chunkserver
            chunkuuid = chunkuuids[i]
            chunkloc = self.master.get_chunkloc(chunkuuid)
            chunkservers[chunkloc].write(chunkuuid, chunks[i])

    def num_chunks(self, size):
        return (size // self.master.chunksize) \
            + (1 if size % self.master.chunksize > 0 else 0)

    def write_append(self, filename, data):
        if not self.exists(filename):
            raise Exception("append error, file does not exist: " \
                 + filename)
        num_append_chunks = self.num_chunks(len(data))
        append_chunkuuids = self.master.alloc_append(filename, \
            num_append_chunks)
        self.write_chunks(append_chunkuuids, data)

    def exists(self, filename):
        return self.master.exists(filename)

    def read(self, filename): # get metadata, then read chunks direct
        if not self.exists(filename):
            raise Exception("read error, file does not exist: " \
                + filename)
        chunks = []
        chunkuuids = self.master.get_chunkuuids(filename)
        chunkservers = self.master.get_chunkservers()
        for chunkuuid in chunkuuids:
            chunkloc = self.master.get_chunkloc(chunkuuid)
            chunk = chunkservers[chunkloc].read(chunkuuid)
            chunks.append(chunk)
        data = reduce(lambda x, y: x + y, chunks) # reassemble in order
        return data

    def delete(self, filename):
        self.master.delete(filename)

class GFSMaster:
    def __init__(self):
        self.num_chunkservers = 5
        self.max_chunkservers = 10
        self.max_chunksperfile = 100
        self.chunksize = 10
        self.chunkrobin = 0
        self.filetable = {} # file to chunk mapping
        self.chunktable = {} # chunkuuid to chunkloc mapping
        self.chunkservers = {} # loc id to chunkserver mapping
        self.init_chunkservers()

    def init_chunkservers(self):
        for i in range(0, self.num_chunkservers):
            chunkserver = GFSChunkserver(i)
            self.chunkservers[i] = chunkserver

    def get_chunkservers(self):
        return self.chunkservers

    def alloc(self, filename, num_chunks): # return ordered chunkuuid list
        chunkuuids = self.alloc_chunks(num_chunks)
        self.filetable[filename] = chunkuuids
        return chunkuuids

    def alloc_chunks(self, num_chunks):
        chunkuuids = []
        for i in range(0, num_chunks):
            chunkuuid = uuid.uuid1()
            chunkloc = self.chunkrobin
            self.chunktable[chunkuuid] = chunkloc
            chunkuuids.append(chunkuuid)
            self.chunkrobin = (self.chunkrobin + 1) % self.num_chunkservers
        return chunkuuids

    def alloc_append(self, filename, num_append_chunks): # append chunks
        chunkuuids = self.filetable[filename]
        append_chunkuuids = self.alloc_chunks(num_append_chunks)
        chunkuuids.extend(append_chunkuuids)
        return append_chunkuuids

    def get_chunkloc(self, chunkuuid):
        return self.chunktable[chunkuuid]

    def get_chunkuuids(self, filename):
        return self.filetable[filename]

    def exists(self, filename):
        return True if filename in self.filetable else False

    def delete(self, filename): # rename for later garbage collection
        chunkuuids = self.filetable[filename]
        del self.filetable[filename]
        timestamp = repr(time.time())
        deleted_filename = "/hidden/deleted/" + timestamp + filename
        self.filetable[deleted_filename] = chunkuuids
        print "deleted file: " + filename + " renamed to " + \
             deleted_filename + " ready for gc"

    def dump_metadata(self):
        print "Filetable:",
        for filename, chunkuuids in self.filetable.items():
            print filename, "with", len(chunkuuids),"chunks"
        print "Chunkservers: ", len(self.chunkservers)
        print "Chunkserver Data:"
        for chunkuuid, chunkloc in sorted(self.chunktable.iteritems(), key=operator.itemgetter(1)):
            chunk = self.chunkservers[chunkloc].read(chunkuuid)
            print chunkloc, chunkuuid, chunk

class GFSChunkserver:
    def __init__(self, chunkloc):
        self.chunkloc = chunkloc
        self.chunktable = {}
        self.local_filesystem_root = "/tmp/gfs/chunks/" + repr(chunkloc)
        if not os.access(self.local_filesystem_root, os.W_OK):
            os.makedirs(self.local_filesystem_root)

    def write(self, chunkuuid, chunk):
        local_filename = self.chunk_filename(chunkuuid)
        with open(local_filename, "w") as f:
            f.write(chunk)
        self.chunktable[chunkuuid] = local_filename

    def read(self, chunkuuid):
        data = None
        local_filename = self.chunk_filename(chunkuuid)
        with open(local_filename, "r") as f:
            data = f.read()
        return data

    def chunk_filename(self, chunkuuid):
        local_filename = self.local_filesystem_root + "/" \
            + str(chunkuuid) + '.gfs'
        return local_filename

def main():
    # test script for filesystem

    # setup
    master = GFSMaster()
    client = GFSClient(master)

    # test write, exist, read
    print "\nWriting..."
    client.write("/usr/python/readme.txt", """
        This file tells you all about python that you ever wanted to know.
        Not every README is as informative as this one, but we aim to please.
        Never yet has there been so much information in so little space.
        """)
    print "File exists? ", client.exists("/usr/python/readme.txt")
    print client.read("/usr/python/readme.txt")

    # test append, read after append
    print "\nAppending..."
    client.write_append("/usr/python/readme.txt", \
        "I'm a little sentence that just snuck in at the end.\n")
    print client.read("/usr/python/readme.txt")

    # test delete
    print "\nDeleting..."
    client.delete("/usr/python/readme.txt")
    print "File exists? ", client.exists("/usr/python/readme.txt")

    # test exceptions
    print "\nTesting Exceptions..."
    try:
        client.read("/usr/python/readme.txt")
    except Exception as e:
        print "This exception should be thrown:", e
    try:
        client.write_append("/usr/python/readme.txt", "foo")
    except Exception as e:
        print "This exception should be thrown:", e

    # show structure of the filesystem
    print "\nMetadata Dump..."
    print master.dump_metadata()

if __name__ == "__main__":
    main()

