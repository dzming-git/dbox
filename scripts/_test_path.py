import sys, os
sys.path.insert(0, r'c:\Users\<用户>\<工作目录>\Claw\Dplayer2.0\src\web')

class FakeLib:
    def __init__(self, db_path, db_file):
        self.db_path = db_path
        self.db_file = db_file
    
    @property
    def full_db_path(self):
        data_dir = os.environ.get('DPLAYER_DATA_DIR')
        if not data_dir:
            _src_web = r'c:\Users\<用户>\<工作目录>\Claw\Dplayer2.0\src\web'
            data_dir = os.path.join(os.path.dirname(os.path.dirname(_src_web)), 'data')
        if os.path.isabs(self.db_path):
            sub = os.path.basename(self.db_path.rstrip('/\\'))
            return os.path.join(data_dir, sub, self.db_file)
        else:
            return os.path.join(data_dir, self.db_path, self.db_file)

lib_rel = FakeLib('libraries', 'porn_girl_1774197682.db')
print('相对路径测试:', lib_rel.full_db_path)
print('文件存在:', os.path.exists(lib_rel.full_db_path))

lib_abs = FakeLib(r'c:\Users\<用户>\<工作目录>\Claw\Dplayer2.0\libraries', 'porn_girl_1774197682.db')
print('绝对路径兼容:', lib_abs.full_db_path)
print('文件存在:', os.path.exists(lib_abs.full_db_path))
