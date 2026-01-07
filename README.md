# A Semantic-Aware Key Matching Method for Data Minimization in Web Applications

This project implements a semantic-aware key matching method designed to detect Excessive Data Exposure (EDE) in web applications. EDE occurs when backend APIs return more data than the frontend actually requires, potentially leading to privacy and security risks. Unlike traditional DOM-based or dynamic analysis methods, our approach uses key matching to directly examine frontend JavaScript/HTML code and API responses at the source level. This enables accurate identification of which response fields are truly used by the application. You can refer to the `paper.pdf` and `slides.pdf` for a more detailed introduction.

## Usage

### Preparation

- Identify the target website, for example: `https://marketplace.alibabacloud.com/products/?categoryId=56698004&label=Software+Infrastructure%2FDataBases&region=`
- Write a configuration file under `config/` folder to trigger the target API and capture its response data, for example: `config/aliyun.config`

```
TARGET /api/ajax/newCommodityList/queryNewList.json?

LOAD https://marketplace.alibabacloud.com/products/?categoryId=56698004&label=Software+Infrastructure%2FDataBases&region=
WAIT_LOCATE //*[@id="market-list"]/section/div/div/div[2]/div/div[2]/div[last()]/div[3]/div/div/div[2]/div[2]/span
TEST aliyun
```

### Testing

- To run basic key matching, execute the command `python3 edetest.py -k {TARGET}`, for example: `python3 edetest.py -k aliyun`

- To run slicing(static) + key matching, execute the command `python3 edetest.py -s {TARGET}`, for example: `python3 edetest.py -s aliyun`

- To run slicing(dynamic) + key matching, execute the command `python3 edetest.py -d {TARGET}`, for example: `python3 edetest.py -d aliyun`

### Results

- For the results of the basic key matching, refer to the flagged file: `result/{TARGET}_flagged.html`, for example: `result/aliyun_flagged.html`

- For the results of the slicing(static) + key matching, refer to the flagged file: `result_static/{TARGET}_flagged.html`, for example: `result_static/aliyun_flagged.html`

- For the results of the slicing(dynamic) + key matching, refer to the flagged file: `result_dynamic/{TARGET}_flagged.html`, for example: `result_dynamic/aliyun_flagged.html`

- The flagged file contains the response data from the target API, Non-EDE data fields is marked in black, while EDE data fields is highlighted in red.
