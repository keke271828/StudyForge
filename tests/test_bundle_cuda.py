from scripts.bundle_cuda import deduplicate_cuda


def file(tmp_path,name,content):
    path=tmp_path/name;path.write_bytes(content);return str(path)


def test_only_identical_nested_cuda_dll_is_removed_and_root_kept(tmp_path):
    a=file(tmp_path,'root',b'same bytes');b=file(tmp_path,'nested',b'same bytes')
    root=('cublas.dll',a,'BINARY');nested=('resources/asr-cuda/nvidia/bin/cublas.dll',b,'BINARY')
    license=('resources/asr-cuda/LICENSE',b,'DATA')
    binaries,datas,removed=deduplicate_cuda([root,nested],[license])
    assert binaries==[root] and datas==[license]
    assert removed[0]['retained']=='cublas.dll' and removed[0]['bytes']==10


def test_different_bytes_and_other_resource_directories_are_preserved(tmp_path):
    a=file(tmp_path,'a',b'123');b=file(tmp_path,'b',b'456')
    rows=[('a.dll',a,'BINARY'),('resources/asr-cuda/bin/a.dll',b,'BINARY'),('other/a.dll',a,'BINARY')]
    assert deduplicate_cuda(rows,[])==(rows,[],[])


def test_native_windows_names_and_missing_or_ambiguous_root_are_safe(tmp_path):
    a=file(tmp_path,'one',b'x');b=file(tmp_path,'two',b'x')
    root=('CUBLAS.DLL',a,'BINARY');nested=('resources\\asr-cuda\\bin\\cublas.dll',b,'DATA')
    assert deduplicate_cuda([root],[nested])[1]==[]
    assert deduplicate_cuda([],[nested])==([],[nested],[])
    ambiguous=[root,('cublas.dll',b,'BINARY')]
    assert deduplicate_cuda(ambiguous,[nested])==(ambiguous,[nested],[])
