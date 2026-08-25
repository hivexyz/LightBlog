// EasyMDE Markdown 编辑器初始化
// 依赖页面中已注入的 csrfToken 变量，以及 marked、katex、renderMathInElement

function initEditor(textareaId, csrfToken) {
    return new EasyMDE({
        element: document.getElementById(textareaId),
        spellChecker: false,
        autosave: { enabled: true, uniqueId: 'post-editor' },
        uploadImage: true,
        imageUploadFunction: function (file, onSuccess, onError) {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('csrf_token', csrfToken);
            fetch('/admin/upload', {
                method: 'POST',
                body: formData
            })
                .then(res => res.json())
                .then(data => {
                    if (data.url) onSuccess(data.url);
                    else onError(data.detail || '上传失败');
                })
                .catch(() => onError('上传失败'));
        },
        previewRender: function (plainText) {
            // 1. 先用 marked 渲染 Markdown（不处理公式）
            const html = window.marked ? window.marked.parse(plainText) : plainText;
            // 2. 创建临时容器，用 KaTeX auto-render 渲染公式
            const temp = document.createElement('div');
            temp.innerHTML = html;
            if (window.renderMathInElement) {
                window.renderMathInElement(temp, {
                    delimiters: [
                        { left: '$$', right: '$$', display: true },
                        { left: '$', right: '$', display: false }
                    ],
                    throwOnError: false
                });
            }
            return temp.innerHTML;
        }
    });
}
